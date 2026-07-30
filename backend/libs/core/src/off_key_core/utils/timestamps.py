"""Shared timestamp parsing for telemetry-producing and consuming services."""

from datetime import UTC, datetime


def parse_utc_timestamp(value: object) -> datetime:
    """Parse a Unix timestamp or ISO-8601 value and normalize it to UTC."""
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC)

    timestamp = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)
