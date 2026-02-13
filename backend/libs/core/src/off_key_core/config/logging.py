from functools import lru_cache

from pydantic import BaseModel, ConfigDict

from .config import get_settings


class LoggingSettings(BaseModel):
    """Logging configuration settings."""

    model_config = ConfigDict(frozen=True)

    LOG_LEVEL: str
    LOG_FORMAT: str
    LOG_CORRELATION_HEADER: str
    ENABLE_REQUEST_LOGGING: bool
    ENABLE_PERFORMANCE_LOGGING: bool


@lru_cache(maxsize=1)
def get_logging_settings() -> LoggingSettings:
    """Return cached LoggingSettings view derived from canonical Settings."""
    settings = get_settings()
    return LoggingSettings(
        LOG_LEVEL=settings.LOG_LEVEL,
        LOG_FORMAT=settings.LOG_FORMAT,
        LOG_CORRELATION_HEADER=settings.LOG_CORRELATION_HEADER,
        ENABLE_REQUEST_LOGGING=settings.ENABLE_REQUEST_LOGGING,
        ENABLE_PERFORMANCE_LOGGING=settings.ENABLE_PERFORMANCE_LOGGING,
    )
