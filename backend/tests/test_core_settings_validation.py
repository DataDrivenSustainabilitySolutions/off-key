import pytest
from pydantic import ValidationError

from off_key_core.config.database import DatabaseSettings
from off_key_core.config.logging import get_logging_settings
from off_key_core.config.runtime import get_runtime_settings


@pytest.fixture(autouse=True)
def clear_core_settings_caches():
    get_logging_settings.cache_clear()
    get_runtime_settings.cache_clear()
    yield
    get_logging_settings.cache_clear()
    get_runtime_settings.cache_clear()


def test_runtime_settings_parse_debug_flag(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    settings = get_runtime_settings()
    assert settings.DEBUG is True
    assert not hasattr(settings, "CHARGER_API_PROVIDER")


def test_logging_settings_normalize_fields(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "warning")
    monkeypatch.setenv("LOG_FORMAT", "JSON")
    monkeypatch.setenv("LOG_CORRELATION_HEADER", "X-Request-ID")

    settings = get_logging_settings()

    assert settings.LOG_LEVEL == "WARNING"
    assert settings.LOG_FORMAT == "json"
    assert settings.LOG_CORRELATION_HEADER == "X-Request-ID"


def test_database_settings_reject_invalid_port():
    with pytest.raises(ValidationError):
        DatabaseSettings(
            POSTGRES_USER="db-user",
            POSTGRES_PASSWORD="db-pass",
            POSTGRES_DB="db",
            POSTGRES_PORT=70000,
            POSTGRES_HOST="localhost",
        )
