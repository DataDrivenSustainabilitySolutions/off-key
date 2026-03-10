"""Tests for RADAR MessageProcessor feature normalization and alignment."""

from unittest.mock import MagicMock

import pytest

from off_key_mqtt_radar.message_processor import MessageProcessor


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

    features = processor._align_features(
        charger_id="charger-1",
        sensor_type="voltage",
        data={"value": 230.5, "quality": 1.0},
    )

    assert features == {"voltage": 230.5}


def test_align_features_uses_sensor_key_when_present():
    processor = _build_processor(required_sensors=set(), state_cache=None)

    features = processor._align_features(
        charger_id="charger-1",
        sensor_type="current",
        data={"current": 18.2, "other": 3.0},
    )

    assert features == {"current": 18.2}


def test_align_features_normalizes_before_state_cache_update():
    state_cache = MagicMock()
    state_cache.update.return_value = {"voltage": 230.5, "current": 18.2}
    processor = _build_processor(
        required_sensors={"voltage", "current"},
        state_cache=state_cache,
    )

    result = processor._align_features(
        charger_id="charger-1",
        sensor_type="voltage",
        data={"value": 230.5},
    )

    state_cache.update.assert_called_once_with(
        "charger-1",
        "voltage",
        {"voltage": 230.5},
    )
    assert result == {"voltage": 230.5, "current": 18.2}


def test_align_features_keeps_full_hierarchy_sensor_key():
    processor = _build_processor(required_sensors=set(), state_cache=None)

    features = processor._align_features(
        charger_id="charger-1",
        sensor_type="TopLevelPart/SubMetricA",
        data={"value": 12.5, "quality": 1.0},
    )

    assert features == {"TopLevelPart/SubMetricA": 12.5}


def test_align_features_passes_full_hierarchy_key_to_state_cache():
    state_cache = MagicMock()
    state_cache.update.return_value = {
        "TopLevelPart/SubMetricA": 12.5,
        "TopLevelPart/SubMetricB": 9.3,
    }
    processor = _build_processor(
        required_sensors={"TopLevelPart/SubMetricA", "TopLevelPart/SubMetricB"},
        state_cache=state_cache,
    )

    result = processor._align_features(
        charger_id="charger-1",
        sensor_type="TopLevelPart/SubMetricA",
        data={"value": 12.5},
    )

    state_cache.update.assert_called_once_with(
        "charger-1",
        "TopLevelPart/SubMetricA",
        {"TopLevelPart/SubMetricA": 12.5},
    )
    assert result == {
        "TopLevelPart/SubMetricA": 12.5,
        "TopLevelPart/SubMetricB": 9.3,
    }


def test_align_features_falls_back_to_first_value_when_sensor_and_value_missing():
    processor = _build_processor(required_sensors=set(), state_cache=None)

    features = processor._align_features(
        charger_id="charger-1",
        sensor_type="voltage",
        data={"other_metric": 7.25, "another_metric": 9.5},
    )

    assert features == {"voltage": 7.25}


def test_align_features_handles_empty_data_without_crashing():
    processor = _build_processor(required_sensors={"voltage"}, state_cache=None)

    features = processor._align_features(
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

    features = processor._align_features(
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
