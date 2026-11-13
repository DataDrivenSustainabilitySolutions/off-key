"""Tests for RADAR MessageProcessor feature normalization and alignment."""

import json
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from off_key_core.schemas.radar import MonitorTiming
from off_key_mqtt_radar.message_processor import MessageProcessor
from off_key_mqtt_radar.models import AnomalyResult, MQTTMessage


def _build_processor(
    required_sensors=None,
    sensor_key_strategy: str = "full_hierarchy",
    **alignment,
) -> MessageProcessor:
    return MessageProcessor(
        detector=MagicMock(),
        feature_validator=MagicMock(),
        memory_manager=MagicMock(),
        required_sensors=required_sensors,
        sensor_key_strategy=sensor_key_strategy,
        **alignment,
    )


def test_align_features_passes_a_single_value_through_without_required_readings():
    processor = _build_processor(required_sensors=set())
    timestamp = datetime.now(UTC).timestamp()

    features, alignment = processor._align_features(
        charger_id="charger-1",
        sensor_type="voltage",
        data={"value": 230.5, "quality": 1.0},
        sample_timestamp=timestamp,
    )

    assert features == {"voltage": 230.5}
    assert alignment["alignment_status"] == "aligned"
    assert alignment["aligned_vector"] is False
    assert alignment["input_timestamps"] == {"voltage": timestamp}


def test_align_features_uses_sensor_key_when_present():
    processor = _build_processor(required_sensors=set())

    features, alignment = processor._align_features(
        charger_id="charger-1",
        sensor_type="current",
        data={"current": 18.2, "other": 3.0},
    )

    assert features == {"current": 18.2}
    assert alignment["aligned_vector"] is False


def test_single_sensor_rejects_queue_delay_using_its_receipt_limit():
    processor = _build_processor(
        required_sensors={"x"}, timing=MonitorTiming(minimum_hold_seconds=0.01)
    )
    features, context = processor._align_features(
        "entity",
        "x",
        {"value": 1},
        sample_timestamp=time.time(),
        received_monotonic=time.monotonic() - 0.02,
    )
    assert features is None
    assert context["rejection_reason"] == "receipt_too_old"


class Clock:
    def __init__(self, now: float = 100.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


def _aligning(sensors, clock, **timing):
    return _build_processor(
        required_sensors=set(sensors),
        timing=MonitorTiming(**timing),
        clock=clock,
        monotonic=clock,
    )


def test_align_features_forms_an_observation_from_every_reading():
    clock = Clock()
    processor = _aligning({"voltage", "current"}, clock)

    features, alignment = processor._align_features(
        "charger-1", "voltage", {"value": 230.5}, sample_timestamp=100.0
    )
    assert features is None
    assert alignment["alignment_status"] == "missing_reading"
    assert alignment["missing_sensors"] == ["current"]

    clock.now = 101.0
    features, alignment = processor._align_features(
        "charger-1", "current", {"value": 18.2}, sample_timestamp=101.0
    )
    assert features == {"voltage": 230.5, "current": 18.2}
    assert alignment["alignment_status"] == "aligned"
    assert alignment["aligned_vector"] is True
    assert alignment["input_timestamps"] == {"voltage": 100.0, "current": 101.0}
    assert alignment["sample_timestamp"] == 101.0
    assert "held_sensors" not in alignment


def test_a_slow_reading_is_held_and_named_in_the_context():
    clock = Clock()
    processor = _aligning({"fast", "slow"}, clock)
    for at in range(100, 230, 10):
        clock.now = at
        processor._align_features("c", "fast", {"value": at}, sample_timestamp=at)
        if at % 60 == 40:
            clock.now = at + 1
            processor._align_features(
                "c", "slow", {"value": at + 1}, sample_timestamp=at + 1
            )
    clock.now = 230
    features, alignment = processor._align_features(
        "c", "fast", {"value": 230}, sample_timestamp=230
    )
    assert features == {"fast": 230, "slow": 221}
    assert alignment["held_sensors"] == ["slow"]


def test_a_reading_that_stops_drops_observations_and_counts_them():
    clock = Clock()
    processor = _aligning(
        {"fast", "slow"}, clock, hold_intervals=3, minimum_hold_seconds=1
    )
    processor.coverage = MagicMock()
    for at in range(100, 190, 10):
        clock.now = at
        processor._align_features("c", "fast", {"value": at}, sample_timestamp=at)
        if at in (100, 120):
            processor._align_features(
                "c", "slow", {"value": at + 1}, sample_timestamp=at + 1
            )
    clock.now = 190
    features, alignment = processor._align_features(
        "c", "fast", {"value": 190}, sample_timestamp=190
    )
    assert features is None
    assert alignment["alignment_status"] == "stale_reading"
    assert alignment["stale_sensors"] == ["slow"]
    processor.coverage.record_drop.assert_called_with("stale_reading")
    assert processor.stale_after_seconds() == {"fast": 30.0, "slow": 60.0}


@pytest.mark.parametrize(
    ("sensor_type", "data", "expected"),
    [
        pytest.param(
            "TopLevelPart/SubMetricA",
            {"value": 12.5, "quality": 1.0},
            {"TopLevelPart/SubMetricA": 12.5},
            id="keeps-full-hierarchy-key",
        ),
        pytest.param(
            "voltage",
            {"other_metric": 7.25, "another_metric": 9.5},
            {"voltage": 7.25},
            id="falls-back-to-first-value",
        ),
    ],
)
def test_align_features_names_the_feature_by_its_sensor(sensor_type, data, expected):
    processor = _build_processor(required_sensors=set())

    features, _ = processor._align_features(
        charger_id="charger-1", sensor_type=sensor_type, data=data
    )

    assert features == expected


def test_align_features_rejects_a_reading_without_a_value():
    processor = _build_processor(required_sensors={"voltage"})

    features, alignment = processor._align_features(
        charger_id="charger-1",
        sensor_type="voltage",
        data={},
    )

    assert features is None
    assert alignment["rejection_reason"] == "observation_without_value"


def test_normalize_sensor_reading_returns_none_for_none_data():
    assert MessageProcessor._normalize_sensor_reading("voltage", None) is None


def test_message_processor_normalizes_sensor_key_strategy():
    processor = _build_processor(sensor_key_strategy="TOP_LEVEL")
    assert processor.sensor_key_strategy == "top_level"


def test_message_processor_rejects_invalid_sensor_key_strategy():
    with pytest.raises(ValueError, match="sensor_key_strategy must be one of"):
        _build_processor(sensor_key_strategy="invalid")


def test_detect_anomaly_uses_canonical_sample_timestamp():
    detector = MagicMock()
    detector.process.return_value = AnomalyResult(
        anomaly_score=0.9,
        is_anomaly=True,
        severity="high",
        timestamp=datetime.now(UTC),
        model_info={},
        raw_data={"sine": 1.0, "cosine": 0.0},
        topic="telemetry/1/sine",
        charger_id="1",
        context={},
    )
    feature_validator = MagicMock()
    memory_manager = MagicMock()
    processor = MessageProcessor(
        detector=detector,
        feature_validator=feature_validator,
        memory_manager=memory_manager,
    )
    message = MQTTMessage(
        topic="telemetry/1/sine",
        payload=b'{"value": 1.0}',
        qos=0,
        retain=False,
    )
    sample_ts = 1_800_000_000.0
    result = processor._detect_anomaly(
        features={"sine": 1.0, "cosine": 0.0},
        message=message,
        charger_id="1",
        alignment_context={
            "aligned_vector": True,
            "alignment_status": "aligned",
            "sample_timestamp": sample_ts - 10,
            "input_timestamps": {
                "sine": sample_ts - 1,
                "cosine": sample_ts,
            },
            "sensor_ages": {"sine": 0.1, "cosine": 0.1},
        },
    )

    assert result.timestamp == datetime.fromtimestamp(sample_ts, tz=UTC)
    assert (
        result.context["canonical_sample_timestamp"]
        == datetime.fromtimestamp(sample_ts, tz=UTC).isoformat()
    )


@pytest.mark.asyncio
async def test_process_message_aligns_evidence_to_payload_event_timestamp():
    detector = MagicMock()
    detector.process.return_value = AnomalyResult(
        anomaly_score=0.1,
        is_anomaly=False,
        severity="low",
        timestamp=datetime.now(UTC),
        model_info={},
        raw_data={"voltage": 230.0},
        topic="telemetry/1/voltage",
        charger_id="1",
        context={},
    )
    feature_validator = MagicMock()
    feature_validator.validate_and_sanitize.return_value = {"value": 230.0}
    memory_manager = MagicMock()
    memory_manager.should_cleanup.return_value = False
    processor = MessageProcessor(
        detector=detector,
        feature_validator=feature_validator,
        memory_manager=memory_manager,
    )
    event_time = datetime.now(UTC) - timedelta(seconds=5)
    message = MQTTMessage(
        topic="telemetry/1/voltage",
        payload=json.dumps(
            {"value": 230.0, "timestamp": event_time.isoformat()}
        ).encode(),
        timestamp=datetime.now(UTC),
    )

    result = processor.process_message_sync(message)

    assert result is not None
    assert result.timestamp == event_time
    assert result.context["canonical_sample_timestamp"] == event_time.isoformat()
    assert result.context["alignment"]["input_timestamps"] == {
        "voltage": event_time.timestamp()
    }
