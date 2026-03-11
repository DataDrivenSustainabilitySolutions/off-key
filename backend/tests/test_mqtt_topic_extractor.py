"""Tests for shared MQTT topic metadata extraction."""

import pytest

from off_key_core.utils.mqtt_topics import TopicMetadataExtractor


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
