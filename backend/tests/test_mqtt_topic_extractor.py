"""Tests for shared MQTT topic metadata extraction."""

import pytest
from off_key_core.utils.mqtt_topics import (
    TopicMetadataExtractor,
    mqtt_topic_filters_overlap,
    normalize_telemetry_topic_filters,
    validate_mqtt_topic_filter,
    validate_telemetry_topic_filter,
)


def test_extracts_canonical_topic_shape():
    extractor = TopicMetadataExtractor()
    metadata = extractor.extract(
        "device/evCharger/0/TopLevel/SubMetric",
        payload={"value": 1},
    )
    assert metadata is not None
    assert metadata.charger_id == "0"
    assert metadata.telemetry_type == "TopLevel/SubMetric"


@pytest.mark.parametrize(
    "topic",
    [
        "device/evCharger/0/voltageAc3",
        "device/evCharger/0/voltageAc",
        "device/evCharger/0/currentDc",
        "device/evCharger/0/voltageAc2",
        "device/evCharger/0/voltageAc1",
    ],
)
def test_extracts_representative_device_topics(topic):
    metadata = TopicMetadataExtractor().extract(topic, payload={"value": 1})
    assert metadata is not None
    assert metadata.charger_id == "0"
    assert metadata.telemetry_type == topic.rsplit("/", 1)[1]


def test_extracts_fluid_topic_with_custom_regex():
    extractor = TopicMetadataExtractor(
        topic_regex=(r"^tenant/(?P<charger_id>[^/]+)/metrics/(?P<telemetry_type>.+)$")
    )
    metadata = extractor.extract("tenant/charger-9/metrics/voltage/a", payload={})
    assert metadata is not None
    assert metadata.charger_id == "charger-9"
    assert metadata.telemetry_type == "voltage/a"


def test_does_not_use_payload_metadata_when_topic_does_not_match():
    extractor = TopicMetadataExtractor()
    metadata = extractor.extract(
        "unknown/topic/shape",
        payload={"charger_id": "charger-x", "telemetry_type": "ampere"},
    )
    assert metadata is None


def test_returns_none_when_neither_topic_nor_payload_has_required_metadata():
    extractor = TopicMetadataExtractor()
    metadata = extractor.extract("unknown/topic/shape", payload={"value": 1.0})
    assert metadata is None


def test_rejects_regex_without_required_named_groups():
    with pytest.raises(ValueError, match="named groups"):
        TopicMetadataExtractor(topic_regex=r"^charger/([^/]+)/(.+)$")


def test_normalizes_and_deduplicates_monitoring_topic_filters():
    topics = normalize_telemetry_topic_filters(
        [
            " device/evCharger/charger-1/sine ",
            "device/evCharger/charger-1/sine",
            "device/#",
        ]
    )

    assert topics == [
        "device/evCharger/charger-1/sine",
        "device/#",
    ]


@pytest.mark.parametrize(
    ("topic", "message"),
    [
        (" ", "must not be empty"),
        ("device//0/sine", "empty levels"),
        ("device/evCharger/0/foo/#/bar", "last level"),
        ("device/evCharger/0/foo#", "must occupy a level"),
        ("device/evCharger/0/foo+bar", "must occupy a level"),
    ],
)
def test_rejects_malformed_mqtt_topic_filters(topic, message):
    with pytest.raises(ValueError, match=message):
        validate_mqtt_topic_filter(topic)


def test_rejects_mqtt_topic_filter_protocol_limits():
    with pytest.raises(ValueError, match="null characters"):
        validate_mqtt_topic_filter("charger/" + chr(0))

    with pytest.raises(ValueError, match="65535-byte limit"):
        validate_mqtt_topic_filter("a" * 65_536)


def test_root_wildcard_requires_explicit_opt_in():
    with pytest.raises(ValueError, match="Root wildcard"):
        validate_mqtt_topic_filter("#")

    assert validate_mqtt_topic_filter("#", allow_root_wildcard=True) == "#"


@pytest.mark.parametrize("topic", ["#", "/#", "tenant/evCharger/0/sine"])
def test_rejects_monitoring_topic_filters_outside_device_namespace(topic):
    with pytest.raises(ValueError):
        validate_telemetry_topic_filter(topic)


@pytest.mark.parametrize(
    "topic",
    [
        "device/evCharger/#",
        "device/evCharger/charger+1/voltageAc",
        "device/evCharger/charger#1/voltageAc",
        "device/evCharger/0/voltage+Ac",
        "device/evCharger/0/voltage#Ac",
        "device/charger/0/status",
        "device/evCharger/0/foo/#/bar",
        "device/evCharger/0/foo+bar",
    ],
)
def test_rejects_invalid_monitoring_topic_filter_shapes(topic):
    with pytest.raises(ValueError):
        validate_telemetry_topic_filter(topic)


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (
            "device/evCharger/+/#",
            "device/evCharger/A/L1",
            True,
        ),
        (
            "device/evCharger/A/+",
            "device/evCharger/A/L1",
            True,
        ),
        (
            "device/evCharger/A/#",
            "device/evCharger/A",
            True,
        ),
        (
            "device/evCharger/A/L1",
            "device/evCharger/B/L1",
            False,
        ),
        (
            "device/evCharger/A/L1",
            "device/other/A/L1",
            False,
        ),
        (
            "device/evCharger/A/L1",
            "device/evCharger/A/L1/phase",
            False,
        ),
    ],
)
def test_detects_mqtt_filter_intersections(left, right, expected):
    assert mqtt_topic_filters_overlap(left, right) is expected
    assert mqtt_topic_filters_overlap(right, left) is expected
