from functools import lru_cache

from pydantic import BaseModel, ConfigDict

from .config import get_settings


class AppSettings(BaseModel):
    """Application-level settings shared across services."""

    model_config = ConfigDict(frozen=True)

    APP_NAME: str
    DEBUG: bool
    CHARGER_API_PROVIDER: str
    CORS_ALLOWED_ORIGINS: tuple[str, ...]


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    """Return cached AppSettings view derived from canonical Settings."""
    settings = get_settings()
    return AppSettings(
        APP_NAME=settings.APP_NAME,
        DEBUG=settings.DEBUG,
        CHARGER_API_PROVIDER=settings.CHARGER_API_PROVIDER,
        CORS_ALLOWED_ORIGINS=tuple(settings.CORS_ALLOWED_ORIGINS),
    )
