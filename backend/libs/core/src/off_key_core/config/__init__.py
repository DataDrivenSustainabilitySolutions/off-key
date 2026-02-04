"""Centralized configuration helpers for off-key core."""

from .telemetry import get_telemetry_settings

# Default retention period - safe constant fallback.
RETENTION_DAYS_DEFAULT = 14


def get_retention_days() -> int:
    """
    Return validated telemetry retention days for use across services.

    The value originates from `TELEMETRY_RETENTION_DAYS` (fallback
    `SYNC_RETENTION_DAYS` for compatibility) and is validated by the
    TelemetrySettings model in :mod:`off_key_core.config.telemetry`.
    """
    return get_telemetry_settings().retention_days


__all__ = ["RETENTION_DAYS_DEFAULT", "get_retention_days"]
