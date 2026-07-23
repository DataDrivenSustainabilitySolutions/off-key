"""Time-related utilities shared by tactic services."""

from datetime import UTC, datetime
from typing import Any


def coerce_utc(value: Any) -> datetime | None:
    """Parse `value` into a timezone-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    try:
        tzinfo = value.tzinfo
    except AttributeError:
        return None

    if tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
