"""
Topic parser utilities for RADAR.
"""

from collections.abc import Mapping
from typing import Any

from off_key_core.utils.mqtt_topics import (
    TopicMetadataExtractor,
    canonical_sensor_key,
    normalize_sensor_key_strategy,
    validate_telemetry_topic_filter,
)


class TopicParser:
    """
    Parse MQTT topics using the shared extraction contract.
    """

    _default_extractor = TopicMetadataExtractor()

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
        strategy = normalize_sensor_key_strategy(sensor_key_strategy)
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
    ) -> set[str]:
        sensors: set[str] = set()
        for topic in topics:
            try:
                normalized = validate_telemetry_topic_filter(topic)
            except ValueError:
                continue
            levels = normalized.split("/")
            offset = 2
            if normalized == "telemetry/#" or any(
                level in {"+", "#"} for level in levels[offset:]
            ):
                continue
            try:
                sensors.add(
                    canonical_sensor_key("/".join(levels[offset:]), sensor_key_strategy)
                )
            except ValueError:
                continue
        return sensors
