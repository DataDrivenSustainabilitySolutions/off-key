from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class LoggingSettings(BaseSettings):
    """Logging configuration settings."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore", frozen=True)

    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "simple"
    LOG_CORRELATION_HEADER: str = "X-Correlation-ID"
    ENABLE_REQUEST_LOGGING: bool = True
    ENABLE_PERFORMANCE_LOGGING: bool = True


@lru_cache(maxsize=1)
def get_logging_settings() -> LoggingSettings:
    """Return cached logging settings."""
    return LoggingSettings()
