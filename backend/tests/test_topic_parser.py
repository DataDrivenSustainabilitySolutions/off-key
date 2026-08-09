"""Tests for RADAR TopicParser feature key extraction."""

import pytest
from off_key_mqtt_radar.topic_parser import TopicParser


def test_extract_sensor_type_uses_full_hierarchy_by_default():
    sensor = TopicParser.extract_sensor_type(
        "device/evCharger/charger-1/TopLevelPart/SubMetricA"
    )
    assert sensor == "TopLevelPart/SubMetricA"


def test_extract_sensor_type_supports_leaf_strategy():
    sensor = TopicParser.extract_sensor_type(
        "device/evCharger/charger-1/TopLevelPart/SubMetricA",
        sensor_key_strategy="leaf",
    )
    assert sensor == "SubMetricA"


def test_extract_sensor_type_supports_top_level_strategy():
    sensor = TopicParser.extract_sensor_type(
        "device/evCharger/charger-1/TopLevelPart/SubMetricA",
        sensor_key_strategy="top_level",
    )
    assert sensor == "TopLevelPart"


def test_derive_required_sensors_uses_full_hierarchy_default():
    topics = [
        "device/evCharger/+/TopLevelPart/SubMetricA",
        "device/evCharger/+/TopLevelPart/SubMetricB",
    ]
    assert TopicParser.derive_required_sensors(topics) == {
        "TopLevelPart/SubMetricA",
        "TopLevelPart/SubMetricB",
    }


def test_derive_required_sensors_supports_leaf_strategy():
    topics = [
        "device/evCharger/+/TopLevelPart/SubMetricA",
        "device/evCharger/+/TopLevelPart/SubMetricB",
    ]
    assert TopicParser.derive_required_sensors(topics, sensor_key_strategy="leaf") == {
        "SubMetricA",
        "SubMetricB",
    }


def test_derive_required_sensors_supports_top_level_strategy():
    topics = [
        "device/evCharger/+/TopLevelPart/SubMetricA",
        "device/evCharger/+/TopLevelPart/SubMetricB",
        "device/evCharger/+/OtherPart/SubMetricC",
    ]
    assert TopicParser.derive_required_sensors(
        topics, sensor_key_strategy="top_level"
    ) == {
        "TopLevelPart",
        "OtherPart",
    }


def test_derive_required_sensors_ignores_wildcard_tail_topics():
    topics = [
        "device/evCharger/+/#",
        "device/evCharger/+/+",
    ]
    assert TopicParser.derive_required_sensors(topics) == set()


def test_extract_sensor_type_rejects_invalid_strategy():
    with pytest.raises(ValueError, match="sensor_key_strategy must be one of"):
        TopicParser.extract_sensor_type(
            "device/evCharger/charger-1/TopLevelPart/SubMetricA",
            sensor_key_strategy="invalid",
        )


def test_extract_sensor_type_requires_device_namespace():
    sensor = TopicParser.extract_sensor_type("charger/charger-1/legacy/TopLevelPart")
    assert sensor is None


def test_extract_charger_id_rejects_payload_fallback_on_regex_miss():
    charger_id = TopicParser.extract_charger_id(
        "tenant-a/site-b/topic",
        payload={"charger_id": "charger-from-payload", "telemetry_type": "voltage"},
    )
    assert charger_id is None


def test_extract_sensor_type_rejects_payload_fallback_on_regex_miss():
    sensor = TopicParser.extract_sensor_type(
        "tenant-a/site-b/topic",
        payload={
            "charger_id": "charger-from-payload",
            "telemetry_type": "metrics/voltage",
        },
    )
    assert sensor is None
