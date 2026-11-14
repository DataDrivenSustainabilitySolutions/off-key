"""Monitoring coverage remains visible independently of traffic and logging."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from off_key_mqtt_radar.coverage import CoverageTracker
from off_key_mqtt_radar.feature_validation import TelemetryFeatureValidator
from off_key_mqtt_radar.health_monitor import HealthMonitor
from off_key_mqtt_radar.message_processor import MessageProcessor
from off_key_mqtt_radar.models import MQTTMessage


def test_coverage_counters_are_thread_safe_and_checkpoint_round_trips():
    tracker = CoverageTracker()

    def receive_and_drop(_index):
        tracker.record_received()
        tracker.record_drop("queue_full")

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(receive_and_drop, range(1100)))
    restored = CoverageTracker(tracker.snapshot().model_dump(mode="json"))
    restored.record_received()
    restored.record_possible_gap("worker_restart")
    snapshot = restored.snapshot()
    assert snapshot.received_message_count == 1101
    assert snapshot.dropped_message_count == 1100
    assert snapshot.dropped_by_reason == {"queue_full": 1100}
    assert snapshot.possible_gap_count == 1
    assert snapshot.has_gaps
    assert snapshot.last_gap_reason == "worker_restart"
    assert snapshot.last_gap_at.utcoffset().total_seconds() == 0
    snapshot.dropped_by_reason.clear()
    assert restored.snapshot().dropped_by_reason == {"queue_full": 1100}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (b"not-json", "invalid_payload"),
        # Valid JSON that is not an object is malformed input, not a crash.
        (b"[1, 2]", "invalid_payload"),
        (b"42", "invalid_payload"),
        (b'{"value": "no-number"}', "invalid_features"),
    ],
)
async def test_invalid_observations_record_coverage_losses(payload, reason):
    tracker = CoverageTracker()
    processor = MessageProcessor(
        detector=None,
        feature_validator=TelemetryFeatureValidator(),
        memory_manager=None,
        coverage=tracker,
    )
    result = processor.process_message_sync(
        MQTTMessage(topic="telemetry/entity/reading", payload=payload)
    )
    assert result is None
    assert tracker.snapshot().dropped_by_reason == {reason: 1}


def test_resumed_traffic_does_not_clear_monitoring_coverage_alert():
    tracker = CoverageTracker()
    tracker.record_received()
    tracker.record_drop("invalid_payload", 100)
    for _ in range(100):
        tracker.record_received()
    monitor = HealthMonitor()
    monitor.started_monotonic = time.monotonic()
    monitor.set_components(
        telemetry_log=SimpleNamespace(
            get_health_status=lambda: {
                "status": "healthy",
                "coverage": tracker.snapshot().model_dump(mode="json"),
            }
        ),
        message_processor=SimpleNamespace(
            get_metrics=lambda: {"message_count": 100, "processed_message_count": 100},
            stale_after_seconds=dict,
        ),
    )
    status = monitor.get_health_status()
    assert status.status == "degraded"
    assert "monitoring_coverage_gap" in status.active_alerts
    operational = status.metrics["operational_status"]
    assert operational["stage"] == "degraded"
    assert operational["coverage"]["dropped_message_count"] == 100
    assert operational["coverage"]["delivery"] == "best_effort"
    assert "cannot be replayed" in operational["detail"]


def test_possible_interruptions_do_not_invent_a_dropped_observation_count():
    tracker = CoverageTracker()
    tracker.record_possible_gap("mqtt_disconnect")
    snapshot = tracker.snapshot()
    assert snapshot.has_gaps
    assert snapshot.possible_gap_count == 1
    assert snapshot.dropped_message_count == 0
    assert snapshot.last_gap_at <= datetime.now(UTC)
