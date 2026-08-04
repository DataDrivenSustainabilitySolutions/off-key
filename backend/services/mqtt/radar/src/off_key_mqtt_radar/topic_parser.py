"""
Topic parser utilities for RADAR.
"""

from collections.abc import Mapping
from typing import Any, ClassVar

from off_key_core.utils.mqtt_topics import (
    SENSOR_KEY_STRATEGIES,
    TopicMetadataExtractor,
    canonical_sensor_key,
    normalize_sensor_key_strategy,
)


class TopicParser:
    """
    Parse MQTT topics using the shared extraction contract.
    """

    SENSOR_KEY_STRATEGIES: ClassVar[frozenset[str]] = SENSOR_KEY_STRATEGIES
    _default_extractor = TopicMetadataExtractor()

    @staticmethod
    def _validate_sensor_key_strategy(sensor_key_strategy: str) -> str:
        return normalize_sensor_key_strategy(sensor_key_strategy)

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
        try:
            return canonical_sensor_key(telemetry_type, strategy)
        except ValueError:
            return None

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
            if sensor is not None:
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
