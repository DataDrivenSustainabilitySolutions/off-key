from functools import lru_cache
from typing import Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from off_key_core.config.validation import validate_environment as _validate_environment

_ALLOWED_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_ALLOWED_LOG_FORMATS = frozenset({"simple", "json"})


class LoggingSettings(BaseSettings):
    """Logging configuration settings."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore", frozen=True)

    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "simple"
    ENVIRONMENT: str = "development"
    LOG_CORRELATION_HEADER: str = "X-Correlation-ID"
    LOG_REDACT_PII: bool = True
    LOG_PII_DEBUG_UNMASK: bool = False
    LOG_HEARTBEAT_INTERVAL_SECONDS: int = 60
    LOG_REPEAT_SUPPRESSION_SECONDS: int = 60
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

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        return _validate_environment(value)

    @field_validator("LOG_CORRELATION_HEADER")
    @classmethod
    def validate_correlation_header(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("LOG_CORRELATION_HEADER must not be empty")
        if any(ch.isspace() for ch in normalized):
            raise ValueError("LOG_CORRELATION_HEADER must not contain whitespace")
        return normalized

    @field_validator("LOG_HEARTBEAT_INTERVAL_SECONDS")
    @classmethod
    def validate_heartbeat_interval(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("LOG_HEARTBEAT_INTERVAL_SECONDS must be > 0")
        return value

    @field_validator("LOG_REPEAT_SUPPRESSION_SECONDS")
    @classmethod
    def validate_repeat_suppression(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("LOG_REPEAT_SUPPRESSION_SECONDS must be > 0")
        return value

    @model_validator(mode="after")
    def validate_pii_unmask_in_environment(self) -> Self:
        if self.ENVIRONMENT == "production" and self.LOG_PII_DEBUG_UNMASK:
            raise ValueError(
                "LOG_PII_DEBUG_UNMASK must be false when ENVIRONMENT=production"
            )
        return self


@lru_cache(maxsize=1)
def get_logging_settings() -> LoggingSettings:
    """Return cached logging settings."""
    return LoggingSettings()
