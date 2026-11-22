"""Time-related utilities shared by tactic services."""

from datetime import datetime
from typing import Any

from off_key_core.utils.timestamps import as_utc


def coerce_utc(value: Any) -> datetime | None:
    """Parse `value` into a timezone-aware UTC datetime, or None when it is not one."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return as_utc(value) if isinstance(value, datetime) else None
