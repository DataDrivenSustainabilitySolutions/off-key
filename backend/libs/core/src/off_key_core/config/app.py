from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class AppSettings(BaseSettings):
    """Application-level settings shared across services."""

    APP_NAME: str = "off_key"
    DEBUG: bool = False

    # API provider configuration
    CHARGER_API_PROVIDER: str = "pionix"

    # CORS defaults (used by API gateway)
    CORS_ALLOWED_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:8000",
            "http://localhost:5173",
        ]
    )


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    """Return cached AppSettings instance."""
    return AppSettings()
