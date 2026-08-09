"""
Utilities for extracting stable metadata from MQTT topics and payloads.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

DEFAULT_TOPIC_REGEX = r"^device/evCharger/(?P<charger_id>[^/]+)/(?P<telemetry_type>.+)$"
SENSOR_KEY_STRATEGIES = frozenset({"full_hierarchy", "top_level", "leaf"})


@dataclass(frozen=True)
class TopicMetadata:
    """Resolved MQTT metadata used across ingestion and anomaly pipelines."""

    charger_id: str
    telemetry_type: str


class TopicMetadataExtractor:
    """
    Resolve charger metadata from the canonical concrete topic.
    """

    def __init__(
        self,
        topic_regex: str = DEFAULT_TOPIC_REGEX,
    ):
        self.topic_regex = topic_regex
        self._compiled_regex = self._compile_topic_regex(topic_regex)

    @staticmethod
    def _compile_topic_regex(topic_regex: str) -> re.Pattern[str]:
        try:
            compiled = re.compile(topic_regex)
        except re.error as exc:
            raise ValueError(f"Invalid MQTT topic regex: {exc}") from exc

        required = {"charger_id", "telemetry_type"}
        groups = set(compiled.groupindex.keys())
        missing = required - groups
        if missing:
            raise ValueError(
                "MQTT topic regex must include named groups: charger_id, "
                f"telemetry_type (missing: {sorted(missing)})"
            )
        return compiled

    @staticmethod
    def _normalize_value(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return str(value)

    def extract(
        self,
        topic: str,
        payload: Mapping[str, Any] | None = None,
    ) -> TopicMetadata | None:
        """
        Extract metadata from a concrete topic; payload metadata is not accepted.
        """
        charger_id: str | None = None
        telemetry_type: str | None = None

        topic_match = self._compiled_regex.match(topic)
        if topic_match:
            charger_id = self._normalize_value(topic_match.group("charger_id"))
            telemetry_type = self._normalize_value(topic_match.group("telemetry_type"))

        if charger_id is None or telemetry_type is None:
            return None
        if any(
            not segment or "+" in segment or "#" in segment
            for segment in (charger_id, *telemetry_type.split("/"))
        ):
            return None

        return TopicMetadata(charger_id=charger_id, telemetry_type=telemetry_type)


def normalize_sensor_key_strategy(value: str) -> str:
    """Validate the shared feature-key projection used by aligned monitoring."""
    normalized = value.strip().lower()
    if normalized not in SENSOR_KEY_STRATEGIES:
        allowed = ", ".join(sorted(SENSOR_KEY_STRATEGIES))
        raise ValueError(f"sensor_key_strategy must be one of: {allowed}")
    return normalized


def canonical_sensor_key(telemetry_type: str, strategy: str) -> str:
    """Project a telemetry hierarchy onto the configured detector feature key."""
    normalized_strategy = normalize_sensor_key_strategy(strategy)
    hierarchy = [segment for segment in telemetry_type.split("/") if segment]
    if not hierarchy or any(segment in {"+", "#"} for segment in hierarchy):
        raise ValueError("Monitoring sensor paths must be concrete and non-empty")
    if normalized_strategy == "top_level":
        return hierarchy[0]
    if normalized_strategy == "leaf":
        return hierarchy[-1]
    return "/".join(hierarchy)


def derive_monitoring_sensor_keys(
    topics: Iterable[str],
    *,
    sensor_key_strategy: str,
) -> list[str]:
    """Derive the exact aligned schema and reject lossy topic collisions."""
    normalized_topics = normalize_static_monitoring_topics(topics)
    extractor = TopicMetadataExtractor()
    keys: list[str] = []
    topics_by_key: dict[str, str] = {}
    for topic in normalized_topics:
        metadata = extractor.extract(topic)
        if metadata is None:
            raise ValueError(f"Cannot derive monitoring sensor metadata from '{topic}'")
        key = canonical_sensor_key(metadata.telemetry_type, sensor_key_strategy)
        previous_topic = topics_by_key.get(key)
        if previous_topic is not None:
            raise ValueError(
                "sensor_key_strategy collapses multiple MQTT topics onto feature "
                f"'{key}': '{previous_topic}' and '{topic}'"
            )
        topics_by_key[key] = topic
        keys.append(key)
    return keys


def validate_mqtt_topic_filter(
    topic: str,
    *,
    allow_root_wildcard: bool = False,
) -> str:
    """Validate and normalize an MQTT subscription filter."""
    normalized = topic.strip()
    if not normalized:
        raise ValueError("MQTT topic filter must not be empty")
    if "\x00" in normalized:
        raise ValueError("MQTT topic filter must not contain null characters")
    if len(normalized.encode("utf-8")) > 65535:
        raise ValueError("MQTT topic filter exceeds MQTT's 65535-byte limit")
    if normalized in {"#", "/#"} and not allow_root_wildcard:
        raise ValueError("Root wildcard subscriptions are not allowed")

    parts = normalized.split("/")
    if any(part == "" for part in parts):
        raise ValueError("MQTT topic filter must not contain empty levels")

    _validate_wildcard_levels(parts)
    return normalized


def _validate_wildcard_levels(levels: list[str]) -> None:
    """Enforce MQTT wildcard placement rules."""
    final_index = len(levels) - 1
    for index, level in enumerate(levels):
        if "#" in level and level != "#":
            raise ValueError("MQTT multi-level wildcard '#' must occupy a level")
        if level == "#" and index != final_index:
            raise ValueError("MQTT multi-level wildcard '#' must be the last level")
        if "+" in level and level != "+":
            raise ValueError("MQTT single-level wildcard '+' must occupy a level")


def validate_telemetry_topic_filter(topic: str) -> str:
    """Validate a filter in the canonical device telemetry namespace."""
    normalized = validate_mqtt_topic_filter(topic)
    if normalized == "device/#":
        return normalized

    levels = normalized.split("/")
    if len(levels) < 4:
        raise ValueError(
            "MQTT telemetry topic filters must use 'device/#' or "
            "'device/evCharger/<id>/<type>'"
        )
    if levels[0] != "device" or levels[1] != "evCharger":
        raise ValueError(
            "MQTT telemetry topic filters must use the device/evCharger namespace"
        )
    return normalized


def normalize_telemetry_topic_filters(topics: Iterable[str]) -> list[str]:
    """Validate, trim, and de-duplicate charger telemetry filters."""
    normalized_topics: list[str] = []
    seen: set[str] = set()
    for topic in topics:
        normalized = validate_telemetry_topic_filter(topic)
        if normalized not in seen:
            normalized_topics.append(normalized)
            seen.add(normalized)

    if not normalized_topics:
        raise ValueError("At least one MQTT topic filter is required")
    return normalized_topics


def normalize_static_monitoring_topics(topics: Iterable[str]) -> list[str]:
    """Validate concrete, single-charger topics for a static feature schema."""
    normalized = normalize_telemetry_topic_filters(topics)
    if any(level in {"+", "#"} for topic in normalized for level in topic.split("/")):
        raise ValueError(
            "Static monitoring requires concrete MQTT topics; wildcards are not "
            "valid sensor assignments"
        )
    charger_ids = {topic.split("/")[2] for topic in normalized}
    if len(charger_ids) != 1:
        raise ValueError(
            "A static monitoring service must belong to exactly one charger"
        )
    return normalized


def mqtt_topic_filters_overlap(left: str, right: str) -> bool:
    """Return whether two valid MQTT filters can match at least one topic.

    Namespace levels are compared literally. ``+`` consumes exactly one level
    and a trailing ``#`` consumes zero or more levels.
    """
    left_levels = validate_mqtt_topic_filter(left, allow_root_wildcard=True).split("/")
    right_levels = validate_mqtt_topic_filter(right, allow_root_wildcard=True).split(
        "/"
    )

    index = 0
    while index < len(left_levels) and index < len(right_levels):
        left_level = left_levels[index]
        right_level = right_levels[index]
        if left_level == "#" or right_level == "#":
            return True
        if left_level != "+" and right_level != "+" and left_level != right_level:
            return False
        index += 1

    if index == len(left_levels) == len(right_levels):
        return True
    if index < len(left_levels):
        return index == len(left_levels) - 1 and left_levels[index] == "#"
    return index == len(right_levels) - 1 and right_levels[index] == "#"
