import pytest
from off_key_core.config.database import DatabaseSettings
from off_key_core.config.logging import get_logging_settings
from off_key_core.config.runtime import get_runtime_settings
from off_key_core.config.validation import validate_environment, validate_settings
from pydantic import BaseModel, ValidationError


def test_runtime_settings_parse_debug_flag(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    settings = get_runtime_settings()
    assert settings.DEBUG is True
    assert not hasattr(settings, "CHARGER_API_PROVIDER")


def test_logging_settings_normalize_fields(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "warning")
    monkeypatch.setenv("LOG_FORMAT", "JSON")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("LOG_CORRELATION_HEADER", "X-Request-ID")
    monkeypatch.setenv("LOG_HEARTBEAT_INTERVAL_SECONDS", "30")
    monkeypatch.setenv("LOG_REPEAT_SUPPRESSION_SECONDS", "15")

    settings = get_logging_settings()

    assert settings.LOG_LEVEL == "WARNING"
    assert settings.LOG_FORMAT == "json"
    assert settings.ENVIRONMENT == "production"
    assert settings.LOG_CORRELATION_HEADER == "X-Request-ID"
    assert settings.LOG_HEARTBEAT_INTERVAL_SECONDS == 30
    assert settings.LOG_REPEAT_SUPPRESSION_SECONDS == 15


def test_logging_settings_reject_pii_unmask_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("LOG_PII_DEBUG_UNMASK", "true")

    with pytest.raises(ValidationError, match="LOG_PII_DEBUG_UNMASK"):
        get_logging_settings()


def test_logging_settings_allow_pii_unmask_in_development(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("LOG_PII_DEBUG_UNMASK", "true")

    settings = get_logging_settings()
    assert settings.LOG_PII_DEBUG_UNMASK is True


def test_database_settings_reject_invalid_port():
    with pytest.raises(ValidationError):
        DatabaseSettings(
            POSTGRES_USER="db-user",
            POSTGRES_PASSWORD="db-pass",
            POSTGRES_DB="db",
            POSTGRES_PORT=70000,
            POSTGRES_HOST="localhost",
        )


def test_environment_names_are_normalized_or_rejected_with_the_allowed_set():
    assert validate_environment(" Production ") == "production"
    with pytest.raises(ValueError, match="development, production, staging, test"):
        validate_environment("prod")


def test_settings_validation_reports_every_failing_group_at_once():
    class Ports(BaseModel):
        port: int

    def invalid_port():
        Ports(port="not-a-port")

    def unavailable_secret():
        raise RuntimeError("secret store unavailable")

    with pytest.raises(RuntimeError) as raised:
        validate_settings(
            [("app", dict), ("ports", invalid_port), ("secrets", unavailable_secret)],
            context="Gateway configuration",
        )

    assert str(raised.value).splitlines() == [
        "Gateway configuration validation failed:",
        "ports: port: Input should be a valid integer, "
        "unable to parse string as an integer",
        "secrets: secret store unavailable",
    ]
