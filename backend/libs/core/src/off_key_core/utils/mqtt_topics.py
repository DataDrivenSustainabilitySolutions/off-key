"""
Utilities for extracting stable metadata from MQTT topics and payloads.
"""

from dataclasses import dataclass
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
