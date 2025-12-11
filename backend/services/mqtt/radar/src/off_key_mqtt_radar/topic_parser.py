"""
Topic Parser for RADAR Service

Utility for parsing MQTT topic patterns and extracting metadata
like charger IDs and sensor types.
"""

from typing import Optional, Set, List


class TopicParser:
    """
    Parser for MQTT topic patterns.

    Expected topic format: charger/<charger_id>/telemetry/<sensor_type>

    Handles wildcards (+, #) appropriately when extracting metadata.
    """

    # Topic segments that should be treated as wildcards
    WILDCARD_SEGMENTS = {"+", "#", "telemetry"}

    @staticmethod
    def extract_charger_id(topic: str) -> Optional[str]:
        """
        Extract charger ID from topic.

        Expected format: charger/<charger_id>/...

        Args:
            topic: MQTT topic string

        Returns:
            Charger ID or None if not found
        """
        try:
            parts = [p for p in topic.split("/") if p]
            if len(parts) >= 2 and parts[0] == "charger":
                charger_id = parts[1]
                if charger_id not in TopicParser.WILDCARD_SEGMENTS:
                    return charger_id
            return None
        except (AttributeError, IndexError):
            return None

    @staticmethod
    def extract_sensor_type(topic: str) -> Optional[str]:
        """
        Extract sensor type from topic.

        Expected format: charger/<id>/telemetry/<sensor_type>
        Falls back to the last non-wildcard segment.

        Args:
            topic: MQTT topic string

        Returns:
            Sensor type or None if not found
        """
        try:
            parts = [p for p in topic.split("/") if p]
            if len(parts) < 3 or parts[0] != "charger":
                return None

            # Prefer the leaf after "telemetry" when present
            if "telemetry" in parts:
                idx = parts.index("telemetry")
                if idx + 1 < len(parts):
                    sensor = parts[idx + 1]
                    if sensor not in TopicParser.WILDCARD_SEGMENTS:
                        return sensor

            # Fallback to last segment
            sensor = parts[-1]
            if sensor not in TopicParser.WILDCARD_SEGMENTS:
                return sensor

            return None
        except (AttributeError, IndexError):
            return None

    @staticmethod
    def derive_required_sensors(topics: List[str]) -> Set[str]:
        """
        Derive required sensor types from subscription topics.

        Used for multi-sensor alignment (wait_for_all mode).

        Args:
            topics: List of subscription topic patterns

        Returns:
            Set of required sensor type names
        """
        sensors: Set[str] = set()

        for topic in topics:
            parts = [p for p in topic.split("/") if p]
            if len(parts) < 4 or parts[0] != "charger":
                continue

            # Prefer the leaf after "telemetry" when present
            if "telemetry" in parts:
                telemetry_idx = parts.index("telemetry")
                if telemetry_idx + 1 < len(parts):
                    candidate = parts[telemetry_idx + 1]
                    if candidate not in TopicParser.WILDCARD_SEGMENTS:
                        sensors.add(candidate)
                        continue

            # Fallback to last segment
            candidate = parts[-1]
            if candidate not in TopicParser.WILDCARD_SEGMENTS:
                sensors.add(candidate)

        return sensors

    @staticmethod
    def build_topic(charger_id: str, sensor_type: str, prefix: str = "charger") -> str:
        """
        Build a topic string from components.

        Args:
            charger_id: Charger identifier
            sensor_type: Sensor type name
            prefix: Topic prefix (default: "charger")

        Returns:
            Formatted topic string
        """
        return f"{prefix}/{charger_id}/telemetry/{sensor_type}"

    @staticmethod
    def matches_pattern(topic: str, pattern: str) -> bool:
        """
        Check if a topic matches a subscription pattern.

        Supports MQTT wildcards:
        - + matches exactly one level
        - # matches any number of levels (must be last)

        Args:
            topic: Actual topic string
            pattern: Subscription pattern with optional wildcards

        Returns:
            True if topic matches pattern
        """
        topic_parts = topic.split("/")
        pattern_parts = pattern.split("/")

        i = 0
        for j, pp in enumerate(pattern_parts):
            if pp == "#":
                # # matches everything remaining
                return True
            if i >= len(topic_parts):
                return False
            if pp == "+":
                # + matches exactly one level
                i += 1
                continue
            if pp != topic_parts[i]:
                return False
            i += 1

        # Must have consumed all topic parts
        return i == len(topic_parts)
