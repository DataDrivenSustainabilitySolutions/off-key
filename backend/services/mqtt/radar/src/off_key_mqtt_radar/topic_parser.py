"""
Topic Parser for RADAR Service

Utility for parsing MQTT topic patterns and extracting metadata
like charger IDs and sensor types.
"""

from typing import Optional, Set, List


class TopicParser:
    """
    Parser for MQTT topic patterns.

    Supported topic formats:
    - charger/<charger_id>/telemetry/<sensor_type>
    - charger/<charger_id>/live-telemetry/<sensor_type>

    Handles wildcards (+, #) appropriately when extracting metadata.
    """

    # Topic segments that should be treated as wildcards
    WILDCARD_SEGMENTS = {"+", "#", "telemetry", "live-telemetry"}

    # Telemetry segment names (used to find sensor type after these segments)
    TELEMETRY_SEGMENTS = {"telemetry", "live-telemetry"}
    SENSOR_KEY_STRATEGIES = {"full_hierarchy", "top_level", "leaf"}

    @staticmethod
    def _validate_sensor_key_strategy(sensor_key_strategy: str) -> str:
        """Validate and normalize sensor key extraction strategy."""
        normalized = sensor_key_strategy.strip().lower()
        if normalized not in TopicParser.SENSOR_KEY_STRATEGIES:
            allowed = ", ".join(sorted(TopicParser.SENSOR_KEY_STRATEGIES))
            raise ValueError(f"sensor_key_strategy must be one of: {allowed}")
        return normalized

    @staticmethod
    def _extract_hierarchy_tail(parts: List[str]) -> Optional[List[str]]:
        """Extract hierarchy tail after telemetry/live-telemetry segment."""
        for i, part in enumerate(parts):
            if part in TopicParser.TELEMETRY_SEGMENTS:
                tail = parts[i + 1 :]
                if tail:
                    return tail
                break
        return None

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
    def extract_sensor_type(
        topic: str, sensor_key_strategy: str = "full_hierarchy"
    ) -> Optional[str]:
        """
        Extract sensor type from topic.

        Supported formats:
        - charger/<id>/telemetry/<sensor_type>
        - charger/<id>/live-telemetry/<sensor_type>

        Supports extraction strategies:
        - full_hierarchy: join all hierarchy tail segments with '/'
        - top_level: use first hierarchy tail segment
        - leaf: use last hierarchy tail segment

        Args:
            topic: MQTT topic string
            sensor_key_strategy: Feature key extraction strategy

        Returns:
            Sensor type or None if not found
        """
        try:
            strategy = TopicParser._validate_sensor_key_strategy(sensor_key_strategy)
            parts = [p for p in topic.split("/") if p]
            if len(parts) < 3 or parts[0] != "charger":
                return None

            hierarchy_tail = TopicParser._extract_hierarchy_tail(parts)
            if hierarchy_tail:
                if any(seg in {"+", "#"} for seg in hierarchy_tail):
                    return None
                if strategy == "top_level":
                    return hierarchy_tail[0]
                if strategy == "leaf":
                    return hierarchy_tail[-1]
                return "/".join(hierarchy_tail)
            return None
        except (AttributeError, IndexError):
            return None

    @staticmethod
    def derive_required_sensors(
        topics: List[str], sensor_key_strategy: str = "full_hierarchy"
    ) -> Set[str]:
        """
        Derive required sensor types from subscription topics.

        Used for multi-sensor alignment (wait_for_all mode).

        Args:
            topics: List of subscription topic patterns
            sensor_key_strategy: Feature key extraction strategy

        Returns:
            Set of required sensor type names
        """
        sensors: Set[str] = set()

        for topic in topics:
            sensor = TopicParser.extract_sensor_type(
                topic, sensor_key_strategy=sensor_key_strategy
            )
            if sensor:
                sensors.add(sensor)

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
