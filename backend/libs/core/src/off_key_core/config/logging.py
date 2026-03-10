from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ALLOWED_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_ALLOWED_LOG_FORMATS = frozenset({"simple", "json"})


class LoggingSettings(BaseSettings):
    """Logging configuration settings."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore", frozen=True)

    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "simple"
    LOG_CORRELATION_HEADER: str = "X-Correlation-ID"
    ENABLE_REQUEST_LOGGING: bool = True
    ENABLE_PERFORMANCE_LOGGING: bool = True

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in _ALLOWED_LOG_LEVELS:
            allowed = ", ".join(sorted(_ALLOWED_LOG_LEVELS))
            raise ValueError(f"LOG_LEVEL must be one of: {allowed}")
        return normalized

    @field_validator("LOG_FORMAT")
    @classmethod
    def validate_log_format(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_LOG_FORMATS:
            allowed = ", ".join(sorted(_ALLOWED_LOG_FORMATS))
            raise ValueError(f"LOG_FORMAT must be one of: {allowed}")
        return normalized

    @field_validator("LOG_CORRELATION_HEADER")
    @classmethod
    def validate_correlation_header(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("LOG_CORRELATION_HEADER must not be empty")
        if any(ch.isspace() for ch in normalized):
            raise ValueError("LOG_CORRELATION_HEADER must not contain whitespace")
        return normalized


@lru_cache(maxsize=1)
def get_logging_settings() -> LoggingSettings:
    """Return cached logging settings."""
    return LoggingSettings()
