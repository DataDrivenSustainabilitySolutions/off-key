"""Configuration for the database schema service."""

from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SyncConfig(BaseModel):
    """Runtime configuration for the db-sync API server."""

    api_host: str
    api_port: int = Field(ge=1, le=65535)

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SyncSettings(BaseSettings):
    """Environment-backed settings for the database schema service."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    SYNC_API_HOST: str = "0.0.0.0"
    SYNC_API_PORT: int = Field(default=8009, ge=1, le=65535)

    @property
    def config(self) -> SyncConfig:
        return SyncConfig(
            api_host=self.SYNC_API_HOST,
            api_port=self.SYNC_API_PORT,
        )


@lru_cache(maxsize=1)
def get_sync_settings() -> SyncSettings:
    """Return cached DB-sync settings instance."""
    return SyncSettings()


def clear_sync_settings_cache() -> None:
    """Clear cached DB-sync settings for tests and local tooling."""
    get_sync_settings.cache_clear()
