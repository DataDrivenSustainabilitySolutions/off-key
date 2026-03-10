"""Tests for RADAR TopicParser feature key extraction."""

import pytest

from off_key_mqtt_radar.topic_parser import TopicParser


def test_extract_sensor_type_uses_full_hierarchy_by_default():
    sensor = TopicParser.extract_sensor_type(
        "charger/charger-1/live-telemetry/TopLevelPart/SubMetricA"
    )
    assert sensor == "TopLevelPart/SubMetricA"


def test_extract_sensor_type_supports_leaf_strategy():
    sensor = TopicParser.extract_sensor_type(
        "charger/charger-1/live-telemetry/TopLevelPart/SubMetricA",
        sensor_key_strategy="leaf",
    )
    assert sensor == "SubMetricA"


def test_extract_sensor_type_supports_top_level_strategy():
    sensor = TopicParser.extract_sensor_type(
        "charger/charger-1/live-telemetry/TopLevelPart/SubMetricA",
        sensor_key_strategy="top_level",
    )
    assert sensor == "TopLevelPart"


def test_derive_required_sensors_uses_full_hierarchy_default():
    topics = [
        "charger/+/live-telemetry/TopLevelPart/SubMetricA",
        "charger/+/live-telemetry/TopLevelPart/SubMetricB",
    ]
    assert TopicParser.derive_required_sensors(topics) == {
        "TopLevelPart/SubMetricA",
        "TopLevelPart/SubMetricB",
    }


def test_derive_required_sensors_supports_leaf_strategy():
    topics = [
        "charger/+/live-telemetry/TopLevelPart/SubMetricA",
        "charger/+/live-telemetry/TopLevelPart/SubMetricB",
    ]
    assert TopicParser.derive_required_sensors(topics, sensor_key_strategy="leaf") == {
        "SubMetricA",
        "SubMetricB",
    }


def test_derive_required_sensors_supports_top_level_strategy():
    topics = [
        "charger/+/live-telemetry/TopLevelPart/SubMetricA",
        "charger/+/live-telemetry/TopLevelPart/SubMetricB",
        "charger/+/live-telemetry/OtherPart/SubMetricC",
    ]
    assert TopicParser.derive_required_sensors(
        topics, sensor_key_strategy="top_level"
    ) == {
        "TopLevelPart",
        "OtherPart",
    }


def test_extract_sensor_type_rejects_invalid_strategy():
    with pytest.raises(ValueError, match="sensor_key_strategy must be one of"):
        TopicParser.extract_sensor_type(
            "charger/charger-1/live-telemetry/TopLevelPart/SubMetricA",
            sensor_key_strategy="invalid",
        )


def test_extract_sensor_type_requires_telemetry_segment():
    sensor = TopicParser.extract_sensor_type("charger/charger-1/legacy/TopLevelPart")
    assert sensor is None
