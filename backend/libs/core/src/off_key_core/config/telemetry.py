from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TelemetrySettings(BaseSettings):
    """Telemetry retention settings shared across services."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore", frozen=True)

    TELEMETRY_RETENTION_DAYS: int = 14
    # Optional ceiling on telemetry and monitoring evidence storage; unset disables.
    TELEMETRY_STORAGE_CAP_GB: float | None = None

    @field_validator("TELEMETRY_RETENTION_DAYS")
    @classmethod
    def validate_retention_days(cls, value: int) -> int:
        if not 1 <= value <= 365:
            raise ValueError("Telemetry retention days must be between 1 and 365")
        return value

    @field_validator("TELEMETRY_STORAGE_CAP_GB", mode="before")
    @classmethod
    def blank_storage_cap_is_unset(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("TELEMETRY_STORAGE_CAP_GB")
    @classmethod
    def validate_storage_cap(cls, value: float | None) -> float | None:
        if value is not None and not 0.1 <= value <= 100_000:
            raise ValueError("Telemetry storage cap must be between 0.1 and 100000 GB")
        return value

    @property
    def retention_days(self) -> int:
        return self.TELEMETRY_RETENTION_DAYS

    @property
    def storage_cap_bytes(self) -> int | None:
        if self.TELEMETRY_STORAGE_CAP_GB is None:
            return None
        return int(self.TELEMETRY_STORAGE_CAP_GB * 1_000_000_000)


@lru_cache(maxsize=1)
def get_telemetry_settings() -> TelemetrySettings:
    """Return cached telemetry settings."""
    return TelemetrySettings()
