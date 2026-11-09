"""Shared timestamp parsing for telemetry-producing and consuming services."""

from datetime import UTC, datetime
from math import isfinite


def as_utc(value: datetime) -> datetime:
    """Read a naive datetime as UTC and convert an aware one to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_utc_timestamp(value: object) -> datetime:
    """Parse a Unix timestamp or ISO-8601 value and normalize it to UTC."""
    if isinstance(value, int | float):
        if isinstance(value, bool) or not isfinite(float(value)):
            raise ValueError("Timestamp must be a finite Unix or ISO-8601 value")
        return datetime.fromtimestamp(value, tz=UTC)

    normalized = str(value).strip()
    if not normalized:
        raise ValueError("Timestamp must not be empty")
    try:
        unix_value = float(normalized)
    except ValueError:
        unix_value = None
    if unix_value is not None:
        if not isfinite(unix_value):
            raise ValueError("Timestamp must be finite")
        return datetime.fromtimestamp(unix_value, tz=UTC)

    return as_utc(datetime.fromisoformat(normalized.replace("Z", "+00:00")))
