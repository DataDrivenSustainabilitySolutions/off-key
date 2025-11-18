"""Centralized configuration helpers for off-key core."""

from dotenv import load_dotenv

from .config import telemetry_settings

# Load .env file to ensure local dev overrides work.
load_dotenv()

# Default retention period for telemetry data (in days)
RETENTION_DAYS_DEFAULT = telemetry_settings.retention_days


def get_retention_days() -> int:
    """
    Return validated telemetry retention days for use across services.

    The value originates from `TELEMETRY_RETENTION_DAYS` (fallback
    `SYNC_RETENTION_DAYS` for compatibility) and is validated by the
    TelemetrySettings model in :mod:`off_key_core.config.config`.
    """

    return telemetry_settings.retention_days


__all__ = ["RETENTION_DAYS_DEFAULT", "get_retention_days", "telemetry_settings"]
