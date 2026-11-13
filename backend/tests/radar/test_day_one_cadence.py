"""The test that breaks the design on day one: one device, one topic per reading.

It runs the real hand-off between the two services that own time:

  TACTIC ingress envelope (received_at = TACTIC wall clock)
    -> mqtt-proxy CollectionBuffer (sample policy, keeps the original receive time)
    -> accepted topic {"value", "timestamp"}
    -> RADAR MessageProcessor + SensorStateCache (strict barrier, PerformanceConfig())

Everything is at its default: the collection interval a reading gets when recording is
switched on, and the timing a monitor gets when it is applied from the composer
(`PipelineActivations._submit` passes `PerformanceConfig()`; the apply request has no
timing field). The clock is simulated, so an hour of telemetry runs in about a second.

The spec it checks is the product's own promise: the composer's startup estimate
(`frontend/src/features/pipelines/startup.ts`, `observationSeconds`) tells the user
"one observation every <most frequent reading interval>". A monitor on two readings
that each arrive every 20 seconds should therefore score about every 20 seconds, and
one on a reading every 10 seconds and one every minute about every 10 seconds.
"""

import json
import time
from collections import Counter
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from off_key_core.schemas.radar import PerformanceConfig
from off_key_core.schemas.system import SystemDocument
from off_key_core.schemas.system_collection import (
    SystemCollectionDefinition,
    build_bindings,
)
from off_key_mqtt_proxy.client.models import MQTTMessage as ProxyMessage
from off_key_mqtt_proxy.collection_buffer import CollectionBuffer
from off_key_mqtt_radar.activity import ActivityTracker, evaluate_activity
from off_key_mqtt_radar.coverage import CoverageTracker
from off_key_mqtt_radar.feature_validation import TelemetryFeatureValidator
from off_key_mqtt_radar.message_processor import MessageProcessor
from off_key_mqtt_radar.models import AnomalyResult
from off_key_mqtt_radar.models import MQTTMessage as RadarMessage
from off_key_mqtt_radar.topic_parser import TopicParser

HOUR = 3600.0
TICK = 0.1  # mqtt-proxy's emit loop period (proxy.py: asyncio.sleep(0.1))


def _device(readings: dict[str, int]) -> SystemCollectionDefinition:
    """One broker, one device, one topic per reading, each with its own interval."""
    document = SystemDocument.model_validate(
        {
            "connections": [{"id": "broker", "label": "Broker", "host": "b.example"}],
            "devices": [
                {"id": "charger-7", "label": "Charger 7", "connection_id": "broker"}
            ],
            "streams": [
                {
                    "id": reading,
                    "label": reading.title(),
                    "connection_id": "broker",
                    "device_id": "charger-7",
                    "topic": f"site/charger-7/{reading}",
                    "value_type": "number",
                    "policy": {"mode": "sample", "interval_seconds": interval},
                }
                for reading, interval in readings.items()
            ],
        }
    )
    return SystemCollectionDefinition(
        document=document, bindings=build_bindings(document), generation="day-one"
    )


def _run_one_hour(publishes: dict[str, tuple[float, float]], intervals: dict[str, int]):
    """Each source publishes `(period, first_offset)`; returns what RADAR did."""
    catalog = _device(intervals)
    streams = {s.definition.id: s for s in catalog.streams(selected_only=True)}
    # Simulated time s maps to a wall clock in the recent past, so the proxy's real
    # "future observation" check in decode_ingress_envelope stays satisfied.
    epoch = time.time() - 2 * HOUR
    now = [0.0]
    wall = lambda: epoch + now[0]  # noqa: E731
    mono = lambda: now[0]  # noqa: E731

    timing = PerformanceConfig()  # what a composer-applied monitor runs with
    topics = [stream.accepted_topic for stream in streams.values()]
    required = TopicParser.derive_required_sensors(topics)
    detector = MagicMock()
    detector.process.side_effect = lambda features, **kw: AnomalyResult(
        anomaly_score=0.0,
        is_anomaly=False,
        severity="low",
        timestamp=datetime.now(UTC),
        model_info={},
        raw_data=dict(features),
        context={},
    )
    processor = MessageProcessor(
        detector=detector,
        feature_validator=TelemetryFeatureValidator(),
        memory_manager=MagicMock(should_cleanup=lambda: False),
        required_sensors=required,
        timing=timing.timing(),
        coverage=CoverageTracker(),
        clock=wall,
        monotonic=mono,
    )
    processor.activity = ActivityTracker(required, clock=mono)
    proxy = CollectionBuffer()
    proxy.configure(catalog, now=0.0)

    due = {reading: offset for reading, (_, offset) in publishes.items()}
    statuses: Counter = Counter()
    forwarded = 0
    steps = int(HOUR / TICK)
    for step in range(steps + 1):
        now[0] = round(step * TICK, 6)
        # 1. Sources publish; TACTIC stamps its wall-clock receipt into the envelope.
        for reading, (period, _) in publishes.items():
            if now[0] + 1e-9 >= due[reading]:
                due[reading] += period
                received = datetime.fromtimestamp(wall(), UTC)
                proxy.receive(
                    ProxyMessage(
                        streams[reading].ingress_topic,
                        {
                            "payload": json.dumps(230.0),
                            "received_at": int(wall() * 1000),
                            "upstream_retained": False,
                        },
                        received,
                        0,
                        False,
                    )
                )
        # 2. mqtt-proxy's emit loop forwards due samples on the accepted topics.
        for observation in proxy.take(now=now[0]):
            accepted = observation.message()
            forwarded += 1
            # 3. RADAR receives it (EMQX hop treated as instantaneous).
            processor.process_message_sync(
                RadarMessage(
                    topic=accepted.topic,
                    payload=json.dumps(accepted.payload).encode(),
                    timestamp=datetime.fromtimestamp(wall(), UTC),
                    received_monotonic=mono(),
                )
            )
            statuses[processor.last_alignment_status] += 1
    # What the operator sees. A detector that never received an observation never
    # leaves warm-up, so health_monitor.py does not expect inference yet.
    seen = evaluate_activity(
        processor.activity.snapshot(),
        stale_after_seconds=processor.stale_after_seconds(),
        inference_expected=False,
        database_health={},
    )
    shown = {
        "coverage_drops": processor.coverage.snapshot().dropped_by_reason,
        "inputs_stalled": seen.inputs_stalled,
        "inference_stalled": seen.inference_stalled,
    }
    return detector.process.call_count, forwarded, statuses, shown


# Readings of one device, each on its own topic: the shape of report-per-topic
# sources (Shelly, Victron, OPC UA and Sparkplug bridges, Digitraffic).
@pytest.mark.parametrize(
    "publishes, intervals",
    [
        pytest.param(
            {"power": (20.0, 5.0), "temperature": (20.0, 8.0)},
            {"power": 10, "temperature": 10},
            id="control-every-20s-3s-apart",
        ),
        pytest.param(
            {"power": (20.0, 5.0), "temperature": (20.0, 15.0)},
            {"power": 10, "temperature": 10},
            id="every-20s-10s-apart",
        ),
        pytest.param(
            {"power": (60.0, 20.0)},
            {"power": 60},
            id="one-reading-recorded-once-a-minute",
        ),
        pytest.param(
            {"power": (10.0, 5.0), "temperature": (60.0, 8.0)},
            {"power": 10, "temperature": 60},
            id="every-10s-and-every-minute",
        ),
    ],
)
def test_a_monitor_scores_once_per_most_frequent_reading_interval(
    publishes, intervals
):
    scored, forwarded, statuses, shown = _run_one_hour(publishes, intervals)

    # The composer's estimate: one observation per most frequent reading interval.
    fastest = min(period for period, _ in publishes.values())
    expected = HOUR / fastest
    assert scored >= 0.9 * expected, (
        f"{forwarded} observations reached RADAR in one hour, {scored} were scored "
        f"(expected about {expected:.0f}). Alignment outcomes: {dict(statuses)}. "
        f"What the monitor shows: {shown}"
    )
    # Nothing was dropped, and the monitor does not look stalled.
    assert shown == {
        "coverage_drops": {},
        "inputs_stalled": False,
        "inference_stalled": False,
    }
