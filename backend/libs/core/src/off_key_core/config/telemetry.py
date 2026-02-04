from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings


class TelemetrySettings(BaseSettings):
    """Telemetry retention settings shared across services."""

    TELEMETRY_RETENTION_DAYS: int = Field(
        14,
        validation_alias=AliasChoices(
            "TELEMETRY_RETENTION_DAYS", "SYNC_RETENTION_DAYS"
        ),
    )

    @field_validator("TELEMETRY_RETENTION_DAYS")
    @classmethod
    def validate_retention_days(cls, v: int) -> int:
        """Ensure telemetry retention stays within a reasonable window."""
        if not 1 <= v <= 365:
            raise ValueError("Telemetry retention days must be between 1 and 365")
        return v

    @property
    def retention_days(self) -> int:
        """Expose a friendlier name used by services."""
        return self.TELEMETRY_RETENTION_DAYS


@lru_cache(maxsize=1)
def get_telemetry_settings() -> TelemetrySettings:
    """Return cached TelemetrySettings instance."""
    return TelemetrySettings()
