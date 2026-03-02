from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TelemetrySettings(BaseSettings):
    """Telemetry retention settings shared across services."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore", frozen=True)

    TELEMETRY_RETENTION_DAYS: int = 14

    @field_validator("TELEMETRY_RETENTION_DAYS")
    @classmethod
    def validate_retention_days(cls, value: int) -> int:
        if not 1 <= value <= 365:
            raise ValueError("Telemetry retention days must be between 1 and 365")
        return value

    @property
    def retention_days(self) -> int:
        return self.TELEMETRY_RETENTION_DAYS


@lru_cache(maxsize=1)
def get_telemetry_settings() -> TelemetrySettings:
    """Return cached telemetry settings."""
    return TelemetrySettings()
