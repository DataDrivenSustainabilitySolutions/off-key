"""Tests for shared MQTT topic metadata extraction."""

import pytest

from off_key_core.utils.mqtt_topics import (
    TopicMetadataExtractor,
    mqtt_topic_filters_overlap,
    normalize_mqtt_topic_filters,
    validate_mqtt_topic_filter,
)


def test_extracts_legacy_topic_shape():
    extractor = TopicMetadataExtractor()
    metadata = extractor.extract(
        "charger/charger-1/live-telemetry/TopLevel/SubMetric",
        payload={"value": 1},
    )
    assert metadata is not None
    assert metadata.charger_id == "charger-1"
    assert metadata.telemetry_type == "TopLevel/SubMetric"


def test_extracts_fluid_topic_with_custom_regex():
    extractor = TopicMetadataExtractor(
        topic_regex=(r"^tenant/(?P<charger_id>[^/]+)/metrics/(?P<telemetry_type>.+)$")
    )
    metadata = extractor.extract("tenant/charger-9/metrics/voltage/a", payload={})
    assert metadata is not None
    assert metadata.charger_id == "charger-9"
    assert metadata.telemetry_type == "voltage/a"


def test_uses_payload_fallback_when_regex_does_not_match():
    extractor = TopicMetadataExtractor()
    metadata = extractor.extract(
        "unknown/topic/shape",
        payload={"charger_id": "charger-x", "telemetry_type": "ampere"},
    )
    assert metadata is not None
    assert metadata.charger_id == "charger-x"
    assert metadata.telemetry_type == "ampere"


def test_returns_none_when_neither_topic_nor_payload_has_required_metadata():
    extractor = TopicMetadataExtractor()
    metadata = extractor.extract("unknown/topic/shape", payload={"value": 1.0})
    assert metadata is None


def test_rejects_regex_without_required_named_groups():
    with pytest.raises(ValueError, match="named groups"):
        TopicMetadataExtractor(topic_regex=r"^charger/([^/]+)/(.+)$")


def test_normalizes_and_deduplicates_monitoring_topic_filters():
    topics = normalize_mqtt_topic_filters(
        [
            " charger/charger-1/live-telemetry/sine ",
            "charger/charger-1/live-telemetry/sine",
            "charger/+/telemetry/#",
        ],
        require_charger_prefix=True,
        require_telemetry_topic=True,
    )

    assert topics == [
        "charger/charger-1/live-telemetry/sine",
        "charger/+/telemetry/#",
    ]


@pytest.mark.parametrize("topic", ["#", "/#", "tenant/charger-1/telemetry/sine"])
def test_rejects_monitoring_topic_filters_outside_charger_namespace(topic):
    with pytest.raises(ValueError):
        validate_mqtt_topic_filter(
            topic,
            require_charger_prefix=True,
            require_telemetry_topic=True,
        )


@pytest.mark.parametrize(
    "topic",
    [
        "charger/#",
        "charger/charger-1/status",
        "charger/charger-1/live-telemetry/foo/#/bar",
        "charger/charger-1/live-telemetry/foo+bar",
    ],
)
def test_rejects_invalid_monitoring_topic_filter_shapes(topic):
    with pytest.raises(ValueError):
        validate_mqtt_topic_filter(
            topic,
            require_charger_prefix=True,
            require_telemetry_topic=True,
        )


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (
            "charger/+/live-telemetry/#",
            "charger/A/live-telemetry/L1",
            True,
        ),
        (
            "charger/A/live-telemetry/+",
            "charger/A/live-telemetry/L1",
            True,
        ),
        (
            "charger/A/live-telemetry/#",
            "charger/A/live-telemetry",
            True,
        ),
        (
            "charger/A/live-telemetry/L1",
            "charger/B/live-telemetry/L1",
            False,
        ),
        (
            "charger/A/telemetry/L1",
            "charger/A/live-telemetry/L1",
            False,
        ),
        (
            "charger/A/live-telemetry/L1",
            "charger/A/live-telemetry/L1/phase",
            False,
        ),
    ],
)
def test_detects_mqtt_filter_intersections(left, right, expected):
    assert mqtt_topic_filters_overlap(left, right) is expected
    assert mqtt_topic_filters_overlap(right, left) is expected
