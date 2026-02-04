from functools import lru_cache

from pydantic_settings import BaseSettings


class LoggingSettings(BaseSettings):
    """Logging configuration settings."""

    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "simple"
    LOG_CORRELATION_HEADER: str = "X-Correlation-ID"
    ENABLE_REQUEST_LOGGING: bool = True
    ENABLE_PERFORMANCE_LOGGING: bool = True


@lru_cache(maxsize=1)
def get_logging_settings() -> LoggingSettings:
    """Return cached LoggingSettings instance."""
    return LoggingSettings()
