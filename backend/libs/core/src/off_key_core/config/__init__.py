"""Centralized configuration for off-key core."""

import os
from dotenv import load_dotenv

# Load .env file to ensure local dev overrides work
load_dotenv()

# Default retention period for telemetry data (in days)
RETENTION_DAYS_DEFAULT = 14


def get_retention_days() -> int:
    """
    Get the retention days configuration from environment or default.

    Returns the number of days to retain telemetry data in TimescaleDB.
    This value is used by both the database retention policy and the
    sync service to ensure consistency.

    Returns:
        int: Number of days to retain data (validated between 1-365)

    Raises:
        ValueError: If the configured value is outside the valid range
    """
    retention_days_str = os.environ.get("SYNC_RETENTION_DAYS")

    if retention_days_str is None:
        return RETENTION_DAYS_DEFAULT

    try:
        retention_days = int(retention_days_str)
    except ValueError:
        raise ValueError(
            f"SYNC_RETENTION_DAYS must be an integer, got: {retention_days_str}"
        )

    if not 1 <= retention_days <= 365:
        raise ValueError(
            f"Retention days must be between 1 and 365, got: {retention_days}"
        )

    return retention_days


__all__ = ["RETENTION_DAYS_DEFAULT", "get_retention_days"]
