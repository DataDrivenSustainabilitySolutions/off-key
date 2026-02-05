"""Centralized configuration helpers for off-key core."""

from dotenv import load_dotenv

# Load .env file to ensure local dev overrides work.
load_dotenv()

# Default retention period - avoid importing config.py which triggers Settings()
RETENTION_DAYS_DEFAULT = 14


def get_retention_days() -> int:
    """
    Return validated telemetry retention days for use across services.

    Uses lazy import to avoid triggering Settings() instantiation on module load.
    The value originates from `TELEMETRY_RETENTION_DAYS` (fallback
    `SYNC_RETENTION_DAYS` for compatibility) and is validated by the
    TelemetrySettings model in :mod:`off_key_core.config.config`.
    """
    from .config import telemetry_settings

    return telemetry_settings.retention_days


__all__ = ["RETENTION_DAYS_DEFAULT", "get_retention_days"]
