from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeSettings(BaseSettings):
    """Runtime behavior settings shared across service internals."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        frozen=True,
    )

    DEBUG: bool = False
    CHARGER_API_PROVIDER: str = "pionix"


@lru_cache(maxsize=1)
def get_runtime_settings() -> RuntimeSettings:
    """Return cached runtime settings."""
    return RuntimeSettings()
