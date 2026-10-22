"""Tests for RADAR MessageProcessor feature normalization and alignment."""

import json
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from off_key_mqtt_radar import state_cache as state_cache_module
from off_key_mqtt_radar.message_processor import MessageProcessor
from off_key_mqtt_radar.models import AnomalyResult, MQTTMessage
from off_key_mqtt_radar.state_cache import AlignmentUpdate, SensorStateCache


def _build_processor(
    required_sensors=None,
    state_cache=None,
    sensor_key_strategy: str = "full_hierarchy",
) -> MessageProcessor:
    detector = MagicMock()
    feature_validator = MagicMock()
    memory_manager = MagicMock()
    return MessageProcessor(
        detector=detector,
        feature_validator=feature_validator,
        memory_manager=memory_manager,
        state_cache=state_cache,
        required_sensors=required_sensors,
        sensor_key_strategy=sensor_key_strategy,
    )


def test_align_features_normalizes_single_sensor_value_key():
    processor = _build_processor(required_sensors=set(), state_cache=None)
    timestamp = datetime.now(UTC).timestamp()

    features, alignment = processor._align_features(
        charger_id="charger-1",
        sensor_type="voltage",
        data={"value": 230.5, "quality": 1.0},
        sample_timestamp=timestamp,
    )

    assert features == {"voltage": 230.5}
    assert alignment["alignment_status"] == "direct_pass_through"
    assert alignment["input_timestamps"] == {"voltage": timestamp}


def test_align_features_uses_sensor_key_when_present():
    processor = _build_processor(required_sensors=set(), state_cache=None)

    features, alignment = processor._align_features(
        charger_id="charger-1",
        sensor_type="current",
        data={"current": 18.2, "other": 3.0},
    )

    assert features == {"current": 18.2}
    assert alignment["aligned_vector"] is False


def test_single_sensor_rejects_queue_delay_using_its_configured_receipt_budget():
    processor = MessageProcessor(
        detector=MagicMock(),
        feature_validator=MagicMock(),
        memory_manager=MagicMock(),
        required_sensors={"x"},
        sensor_freshness_seconds=0.01,
        observation_max_age_seconds=30,
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


def test_align_features_normalizes_before_state_cache_update():
    state_cache = MagicMock()
    state_cache.update_with_status.return_value = AlignmentUpdate(
        status="aligned_emit",
        features={"voltage": 230.5, "current": 18.2},
        sensor_ages={"voltage": 0.4, "current": 0.2},
        input_timestamps={"voltage": 10.0, "current": 11.0},
        sample_timestamp=11.0,
    )
    processor = _build_processor(
        required_sensors={"voltage", "current"},
        state_cache=state_cache,
    )

    features, alignment = processor._align_features(
        charger_id="charger-1",
        sensor_type="voltage",
        data={"value": 230.5},
    )

    state_cache.update_with_status.assert_called_once_with(
        "charger-1",
        "voltage",
        {"voltage": 230.5},
        sample_timestamp=None,
    )
    assert features == {"voltage": 230.5, "current": 18.2}
    assert alignment["alignment_status"] == "aligned_emit"
    assert alignment["aligned_vector"] is True
    assert alignment["input_timestamps"] == {"voltage": 10.0, "current": 11.0}


@pytest.mark.parametrize(
    ("status", "pending_field", "sensor_ages"),
    [
        ("waiting_for_all", "missing_sensors", {"voltage": 0.2}),
        ("stale_sensor_block", "stale_sensors", {"voltage": 0.4, "current": 45.0}),
        ("waiting_for_barrier", "pending_sensors", {"voltage": 0.1, "current": 0.0}),
    ],
)
def test_align_features_withholds_incomplete_vectors(
    status, pending_field, sensor_ages
):
    state_cache = MagicMock()
    state_cache.update_with_status.return_value = AlignmentUpdate(
        status=status, sensor_ages=sensor_ages, **{pending_field: ("current",)}
    )
    processor = _build_processor(
        required_sensors={"voltage", "current"},
        state_cache=state_cache,
    )

    features, alignment = processor._align_features(
        charger_id="charger-1",
        sensor_type="voltage",
        data={"value": 230.5},
    )

    assert features is None
    assert alignment["alignment_status"] == status
    assert alignment[pending_field] == ["current"]


def test_three_sensor_cadence_blocks_stale_vectors_until_the_slow_sensor_recovers(
    monkeypatch,
):
    now = {"value": 100.0}
    monkeypatch.setattr(state_cache_module.time, "time", lambda: now["value"])
    sensors = {"s1", "s2", "s3"}
    processor = _build_processor(
        required_sensors=sensors,
        state_cache=SensorStateCache(
            required_sensors=sensors, max_sensor_age_seconds=5
        ),
    )
    timeline = [
        (100.0, "s1", 1.0, "waiting_for_all", None),
        (101.0, "s2", 2.0, "waiting_for_all", None),
        (102.0, "s3", 3.0, "aligned_emit", {"s1": 1.0, "s2": 2.0, "s3": 3.0}),
        # s1 arrives late; s2 and s3 are now stale and must be blocked.
        (110.0, "s1", 1.1, "stale_sensor_block", None),
        (111.0, "s2", 2.1, "stale_sensor_block", None),
        # Once the slow sensor recovers, aligned vectors resume.
        (112.0, "s3", 3.1, "aligned_emit", {"s1": 1.1, "s2": 2.1, "s3": 3.1}),
    ]

    for at, sensor, value, status, expected in timeline:
        now["value"] = at
        features, alignment = processor._align_features(
            "charger-1", sensor, {sensor: value}
        )
        assert (alignment["alignment_status"], features) == (status, expected)


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
    processor = _build_processor(required_sensors=set(), state_cache=None)

    features, _ = processor._align_features(
        charger_id="charger-1", sensor_type=sensor_type, data=data
    )

    assert features == expected


def test_align_features_handles_empty_data_without_crashing():
    processor = _build_processor(required_sensors={"voltage"}, state_cache=None)

    features, _ = processor._align_features(
        charger_id="charger-1",
        sensor_type="voltage",
        data={},
    )

    assert features == {}


def test_normalize_sensor_reading_returns_none_for_none_data():
    assert MessageProcessor._normalize_sensor_reading("voltage", None) is None


def test_align_features_skips_state_cache_when_cache_missing():
    processor = _build_processor(
        required_sensors={"voltage", "current"},
        state_cache=None,
    )

    features, _ = processor._align_features(
        charger_id="charger-1",
        sensor_type="voltage",
        data={"value": 230.5},
    )

    assert features == {"voltage": 230.5}


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
            "alignment_status": "aligned_emit",
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
