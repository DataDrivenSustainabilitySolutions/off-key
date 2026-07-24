"""
Topic parser utilities for RADAR.
"""

from collections.abc import Mapping
from typing import Any, ClassVar

from off_key_core.utils.mqtt_topics import TopicMetadataExtractor


class TopicParser:
    """
    Parse MQTT topics using the shared extraction contract.
    """

    SENSOR_KEY_STRATEGIES: ClassVar[set[str]] = {
        "full_hierarchy",
        "top_level",
        "leaf",
    }
    _default_extractor = TopicMetadataExtractor()

    @staticmethod
    def _validate_sensor_key_strategy(sensor_key_strategy: str) -> str:
        normalized = sensor_key_strategy.strip().lower()
        if normalized not in TopicParser.SENSOR_KEY_STRATEGIES:
            allowed = ", ".join(sorted(TopicParser.SENSOR_KEY_STRATEGIES))
            raise ValueError(f"sensor_key_strategy must be one of: {allowed}")
        return normalized

    @staticmethod
    def extract_charger_id(
        topic: str,
        payload: Mapping[str, Any] | None = None,
        extractor: TopicMetadataExtractor | None = None,
    ) -> str | None:
        parser = extractor or TopicParser._default_extractor
        metadata = parser.extract(topic=topic, payload=payload)
        if not metadata or metadata.charger_id in {"+", "#"}:
            return None
        return metadata.charger_id

    @staticmethod
    def extract_sensor_type(
        topic: str,
        sensor_key_strategy: str = "full_hierarchy",
        payload: Mapping[str, Any] | None = None,
        extractor: TopicMetadataExtractor | None = None,
    ) -> str | None:
        strategy = TopicParser._validate_sensor_key_strategy(sensor_key_strategy)
        parser = extractor or TopicParser._default_extractor
        metadata = parser.extract(topic=topic, payload=payload)
        if not metadata:
            return None

        telemetry_type = metadata.telemetry_type
        hierarchy_tail = [segment for segment in telemetry_type.split("/") if segment]
        if not hierarchy_tail:
            return None
        if any(segment in {"+", "#"} for segment in hierarchy_tail):
            return None

        if strategy == "top_level":
            return hierarchy_tail[0]
        if strategy == "leaf":
            return hierarchy_tail[-1]
        return "/".join(hierarchy_tail)

    @staticmethod
    def derive_required_sensors(
        topics: list[str],
        sensor_key_strategy: str = "full_hierarchy",
        extractor: TopicMetadataExtractor | None = None,
    ) -> set[str]:
        sensors: set[str] = set()
        for topic in topics:
            sensor = TopicParser.extract_sensor_type(
                topic,
                sensor_key_strategy=sensor_key_strategy,
                payload=None,
                extractor=extractor,
            )
            if sensor:
                sensors.add(sensor)
        return sensors

    @staticmethod
    def build_topic(charger_id: str, sensor_type: str, prefix: str = "charger") -> str:
        return f"{prefix}/{charger_id}/telemetry/{sensor_type}"

    @staticmethod
    def matches_pattern(topic: str, pattern: str) -> bool:
        topic_parts = topic.split("/")
        pattern_parts = pattern.split("/")

        i = 0
        for pp in pattern_parts:
            if pp == "#":
                return True
            if i >= len(topic_parts):
                return False
            if pp == "+":
                i += 1
                continue
            if pp != topic_parts[i]:
                return False
            i += 1

        return i == len(topic_parts)
