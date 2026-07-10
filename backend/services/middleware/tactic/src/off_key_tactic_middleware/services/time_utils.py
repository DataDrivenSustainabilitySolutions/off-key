"""Time-related utilities shared by tactic services."""

from datetime import datetime, timezone
from typing import Any, Optional


def coerce_utc(value: Any) -> Optional[datetime]:
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
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
