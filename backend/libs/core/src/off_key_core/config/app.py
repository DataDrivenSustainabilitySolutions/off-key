from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Application-level settings shared across services."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        frozen=True,
    )

    APP_NAME: str
    CORS_ALLOWED_ORIGINS: tuple[str, ...] = (
        "http://localhost:8000",
        "http://localhost:5173",
    )


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    """Return cached app-level settings."""
    return AppSettings()
