"""
Utilities for extracting stable metadata from MQTT topics and payloads.
"""

from dataclasses import dataclass
from collections.abc import Iterable
import re
from typing import Any, Mapping, Optional


DEFAULT_TOPIC_REGEX = (
    r"^charger/(?P<charger_id>[^/]+)/(?:telemetry|live-telemetry)/"
    r"(?P<telemetry_type>.+)$"
)


@dataclass(frozen=True)
class TopicMetadata:
    """Resolved MQTT metadata used across ingestion and anomaly pipelines."""

    charger_id: str
    telemetry_type: str


class TopicMetadataExtractor:
    """
    Resolve charger metadata from topic first, then payload fallback keys.
    """

    def __init__(
        self,
        topic_regex: str = DEFAULT_TOPIC_REGEX,
        payload_charger_key: str = "charger_id",
        payload_type_key: str = "telemetry_type",
    ):
        self.topic_regex = topic_regex
        self.payload_charger_key = payload_charger_key
        self.payload_type_key = payload_type_key
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
    def _normalize_value(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return str(value)

    def extract(
        self,
        topic: str,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> Optional[TopicMetadata]:
        """
        Extract metadata using regex first, then payload fallback.
        """
        charger_id: Optional[str] = None
        telemetry_type: Optional[str] = None

        topic_match = self._compiled_regex.match(topic)
        if topic_match:
            charger_id = self._normalize_value(topic_match.group("charger_id"))
            telemetry_type = self._normalize_value(topic_match.group("telemetry_type"))

        payload_mapping = payload or {}
        if charger_id is None:
            charger_id = self._normalize_value(
                payload_mapping.get(self.payload_charger_key)
            )
        if telemetry_type is None:
            telemetry_type = self._normalize_value(
                payload_mapping.get(self.payload_type_key)
            )

        if charger_id is None or telemetry_type is None:
            return None

        return TopicMetadata(charger_id=charger_id, telemetry_type=telemetry_type)


def validate_mqtt_topic_filter(
    topic: str,
    *,
    require_charger_prefix: bool = False,
    require_telemetry_topic: bool = False,
    allow_root_wildcard: bool = False,
) -> str:
    """Validate and normalize an MQTT subscription filter for this domain."""
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

    for index, part in enumerate(parts):
        if "#" in part:
            if part != "#":
                raise ValueError("MQTT multi-level wildcard '#' must occupy a level")
            if index != len(parts) - 1:
                raise ValueError("MQTT multi-level wildcard '#' must be the last level")
        if "+" in part and part != "+":
            raise ValueError("MQTT single-level wildcard '+' must occupy a level")

    if require_charger_prefix and parts[0] != "charger":
        raise ValueError("MQTT topic filter must start with 'charger/'")

    if require_telemetry_topic:
        if len(parts) < 4:
            raise ValueError(
                "MQTT telemetry topic filters must use "
                "'charger/<id>/telemetry/<type>' or "
                "'charger/<id>/live-telemetry/<type>'"
            )
        if parts[0] != "charger" or parts[2] not in {"telemetry", "live-telemetry"}:
            raise ValueError(
                "MQTT telemetry topic filters must use the charger telemetry namespace"
            )

    return normalized


def normalize_mqtt_topic_filters(
    topics: Iterable[str],
    *,
    require_charger_prefix: bool = False,
    require_telemetry_topic: bool = False,
    allow_root_wildcard: bool = False,
) -> list[str]:
    """Validate, trim, and de-duplicate MQTT subscription filters."""
    normalized_topics: list[str] = []
    seen: set[str] = set()
    for topic in topics:
        normalized = validate_mqtt_topic_filter(
            topic,
            require_charger_prefix=require_charger_prefix,
            require_telemetry_topic=require_telemetry_topic,
            allow_root_wildcard=allow_root_wildcard,
        )
        if normalized not in seen:
            normalized_topics.append(normalized)
            seen.add(normalized)

    if not normalized_topics:
        raise ValueError("At least one MQTT topic filter is required")
    return normalized_topics
