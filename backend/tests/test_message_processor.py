"""Tests for RADAR MessageProcessor feature normalization and alignment."""

from unittest.mock import MagicMock
from datetime import datetime, timezone

import pytest

from off_key_mqtt_radar.message_processor import MessageProcessor
from off_key_mqtt_radar.state_cache import AlignmentUpdate
from off_key_mqtt_radar.models import AnomalyResult, MQTTMessage


def _build_processor(
    required_sensors=None,
    state_cache=None,
    sensor_key_strategy: str = "full_hierarchy",
) -> MessageProcessor:
    detector = MagicMock()
    security_validator = MagicMock()
    memory_manager = MagicMock()
    return MessageProcessor(
        detector=detector,
        security_validator=security_validator,
        memory_manager=memory_manager,
        state_cache=state_cache,
        required_sensors=required_sensors,
        sensor_key_strategy=sensor_key_strategy,
    )


def test_align_features_normalizes_single_sensor_value_key():
    processor = _build_processor(required_sensors=set(), state_cache=None)

    features, alignment = processor._align_features(
        charger_id="charger-1",
        sensor_type="voltage",
        data={"value": 230.5, "quality": 1.0},
    )

    assert features == {"voltage": 230.5}
    assert alignment["alignment_status"] == "direct_pass_through"


def test_align_features_uses_sensor_key_when_present():
    processor = _build_processor(required_sensors=set(), state_cache=None)

    features, alignment = processor._align_features(
        charger_id="charger-1",
        sensor_type="current",
        data={"current": 18.2, "other": 3.0},
    )

    assert features == {"current": 18.2}
    assert alignment["aligned_vector"] is False


def test_align_features_normalizes_before_state_cache_update():
    state_cache = MagicMock()
    state_cache.update_with_status.return_value = AlignmentUpdate(
        status="aligned_emit",
        features={"voltage": 230.5, "current": 18.2},
        sensor_ages={"voltage": 0.4, "current": 0.2},
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
    )
    assert features == {"voltage": 230.5, "current": 18.2}
    assert alignment["alignment_status"] == "aligned_emit"
    assert alignment["aligned_vector"] is True


def test_align_features_waiting_for_all_returns_none():
    state_cache = MagicMock()
    state_cache.update_with_status.return_value = AlignmentUpdate(
        status="waiting_for_all",
        missing_sensors=("current",),
        sensor_ages={"voltage": 0.2},
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
    assert alignment["alignment_status"] == "waiting_for_all"
    assert alignment["missing_sensors"] == ["current"]


def test_align_features_blocks_stale_sensor_data():
    state_cache = MagicMock()
    state_cache.update_with_status.return_value = AlignmentUpdate(
        status="stale_sensor_block",
        stale_sensors=("current",),
        sensor_ages={"voltage": 0.4, "current": 45.0},
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
    assert alignment["alignment_status"] == "stale_sensor_block"
    assert alignment["stale_sensors"] == ["current"]


def test_align_features_waiting_for_barrier_returns_none():
    state_cache = MagicMock()
    state_cache.alignment_mode = "strict_barrier"
    state_cache.update_with_status.return_value = AlignmentUpdate(
        status="waiting_for_barrier",
        pending_sensors=("current",),
        sensor_ages={"voltage": 0.1, "current": 0.0},
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
    assert alignment["alignment_status"] == "waiting_for_barrier"
    assert alignment["pending_sensors"] == ["current"]


def test_align_features_keeps_full_hierarchy_sensor_key():
    processor = _build_processor(required_sensors=set(), state_cache=None)

    features, _ = processor._align_features(
        charger_id="charger-1",
        sensor_type="TopLevelPart/SubMetricA",
        data={"value": 12.5, "quality": 1.0},
    )

    assert features == {"TopLevelPart/SubMetricA": 12.5}


def test_align_features_falls_back_to_first_value_when_sensor_and_value_missing():
    processor = _build_processor(required_sensors=set(), state_cache=None)

    features, _ = processor._align_features(
        charger_id="charger-1",
        sensor_type="voltage",
        data={"other_metric": 7.25, "another_metric": 9.5},
    )

    assert features == {"voltage": 7.25}


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
    detector.process_with_resilience.return_value = AnomalyResult(
        anomaly_score=0.9,
        is_anomaly=True,
        severity="high",
        timestamp=datetime.now(timezone.utc),
        model_info={},
        raw_data={"sine": 1.0, "cosine": 0.0},
        topic="charger/1/live-telemetry/sine",
        charger_id="1",
        context={},
    )
    security_validator = MagicMock()
    memory_manager = MagicMock()
    processor = MessageProcessor(
        detector=detector,
        security_validator=security_validator,
        memory_manager=memory_manager,
    )
    message = MQTTMessage(
        topic="charger/1/live-telemetry/sine",
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
            "sample_timestamp": sample_ts,
            "sensor_ages": {"sine": 0.1, "cosine": 0.1},
        },
    )

    assert result.timestamp == datetime.fromtimestamp(sample_ts, tz=timezone.utc)
    assert (
        result.context["canonical_sample_timestamp"]
        == datetime.fromtimestamp(sample_ts, tz=timezone.utc).isoformat()
    )
