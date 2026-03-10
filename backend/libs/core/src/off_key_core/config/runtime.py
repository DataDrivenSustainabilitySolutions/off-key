from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_SUPPORTED_CHARGER_API_PROVIDERS = frozenset({"pionix"})


class RuntimeSettings(BaseSettings):
    """Runtime behavior settings shared across service internals."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        frozen=True,
    )

    DEBUG: bool = False
    CHARGER_API_PROVIDER: str = "pionix"

    @field_validator("CHARGER_API_PROVIDER")
    @classmethod
    def validate_charger_api_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _SUPPORTED_CHARGER_API_PROVIDERS:
            allowed = ", ".join(sorted(_SUPPORTED_CHARGER_API_PROVIDERS))
            raise ValueError(f"CHARGER_API_PROVIDER must be one of: {allowed}")
        return normalized


@lru_cache(maxsize=1)
def get_runtime_settings() -> RuntimeSettings:
    """Return cached runtime settings."""
    return RuntimeSettings()
