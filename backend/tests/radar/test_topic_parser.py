"""Tests for RADAR TopicParser feature key extraction."""

import pytest
from off_key_mqtt_radar.topic_parser import TopicParser

TOPIC = "telemetry/charger-1/TopLevelPart/SubMetricA"


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        ("full_hierarchy", "TopLevelPart/SubMetricA"),
        ("leaf", "SubMetricA"),
        ("top_level", "TopLevelPart"),
    ],
)
def test_extract_sensor_type_applies_the_key_strategy(strategy, expected):
    assert TopicParser.extract_sensor_type(TOPIC, sensor_key_strategy=strategy) == (
        expected
    )


def test_extract_sensor_type_defaults_to_the_full_hierarchy():
    assert TopicParser.extract_sensor_type(TOPIC) == "TopLevelPart/SubMetricA"


def test_extract_sensor_type_rejects_invalid_strategy():
    with pytest.raises(ValueError, match="sensor_key_strategy must be one of"):
        TopicParser.extract_sensor_type(TOPIC, sensor_key_strategy="invalid")


@pytest.mark.parametrize(
    ("topic", "payload"),
    [
        ("charger/charger-1/legacy/TopLevelPart", None),
        (
            "tenant-a/site-b/topic",
            {"charger_id": "charger-from-payload", "telemetry_type": "metrics/v"},
        ),
    ],
    ids=["outside_device_namespace", "payload_fallback_on_regex_miss"],
)
def test_sensor_and_charger_are_never_taken_from_unmatched_topics(topic, payload):
    assert TopicParser.extract_sensor_type(topic, payload=payload) is None
    assert TopicParser.extract_charger_id(topic, payload=payload) is None


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        ("full_hierarchy", {"TopLevelPart/SubMetricA", "OtherPart/SubMetricC"}),
        ("leaf", {"SubMetricA", "SubMetricC"}),
        ("top_level", {"TopLevelPart", "OtherPart"}),
    ],
)
def test_derive_required_sensors_keys_explicit_topics_only(strategy, expected):
    topics = [
        "telemetry/+/TopLevelPart/SubMetricA",
        "telemetry/+/OtherPart/SubMetricC",
        # Wildcard tails cannot name a required sensor; invalid filters are ignored.
        "telemetry/+/#",
        "telemetry/+/+",
        "telemetry/#",
        "device/+/voltage",
    ]

    assert TopicParser.derive_required_sensors(topics, strategy) == expected
