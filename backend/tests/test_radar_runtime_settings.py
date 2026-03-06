import pytest
from pydantic import ValidationError

from off_key_mqtt_radar.config.runtime import (
    clear_radar_runtime_settings_cache,
    get_radar_checkpoint_settings,
    get_radar_database_settings,
    get_radar_tactic_client_settings,
)


@pytest.fixture(autouse=True)
def clear_radar_runtime_caches():
    clear_radar_runtime_settings_cache()
    yield
    clear_radar_runtime_settings_cache()


def test_radar_database_settings_build_url_from_postgres_env(monkeypatch):
    monkeypatch.delenv("RADAR_DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_USER", "db@user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss")
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "radar")

    settings = get_radar_database_settings()

    assert (
        settings.async_database_url
        == "postgresql+asyncpg://db%40user:p%40ss@localhost:5432/radar"
    )


def test_radar_database_settings_prefers_direct_url(monkeypatch):
    monkeypatch.setenv("RADAR_DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.delenv("POSTGRES_PORT", raising=False)
    monkeypatch.delenv("POSTGRES_DB", raising=False)

    settings = get_radar_database_settings()

    assert settings.async_database_url == "postgresql+asyncpg://u:p@h:5432/d"


def test_radar_database_settings_direct_url_ignores_invalid_fallback_port(monkeypatch):
    monkeypatch.setenv("RADAR_DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
    monkeypatch.setenv("POSTGRES_PORT", "not-a-port")

    settings = get_radar_database_settings()

    assert settings.async_database_url == "postgresql+asyncpg://u:p@h:5432/d"


def test_radar_database_settings_rejects_sync_direct_url(monkeypatch):
    monkeypatch.setenv("RADAR_DATABASE_URL", "postgresql://u:p@h:5432/d")

    with pytest.raises(ValidationError, match="postgresql\\+asyncpg://"):
        get_radar_database_settings()


def test_radar_database_settings_rejects_incomplete_postgres_env(monkeypatch):
    monkeypatch.delenv("RADAR_DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_USER", "db-user")
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "radar")

    with pytest.raises(ValidationError):
        get_radar_database_settings()


def test_radar_tactic_client_settings_base_url_precedence(monkeypatch):
    monkeypatch.setenv("RADAR_TACTIC_BASE_URL", "http://custom-tactic:9000/")
    monkeypatch.setenv("TACTIC_SERVICE_BASE_URL", "http://ignored:8000")

    settings = get_radar_tactic_client_settings()

    assert settings.base_url == "http://custom-tactic:9000"


def test_radar_tactic_client_settings_base_url_ignores_invalid_fallback_port(
    monkeypatch,
):
    monkeypatch.setenv("RADAR_TACTIC_BASE_URL", "http://custom-tactic:9000/")
    monkeypatch.setenv("TACTIC_SERVICE_PORT", "invalid-port")
    monkeypatch.setenv("RADAR_TACTIC_SERVICE_PORT", "still-invalid")

    settings = get_radar_tactic_client_settings()

    assert settings.base_url == "http://custom-tactic:9000"


def test_radar_tactic_client_settings_cache_ttl_precedence(monkeypatch):
    monkeypatch.setenv("RADAR_TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS", "90")
    monkeypatch.setenv("TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS", "60")

    settings = get_radar_tactic_client_settings()

    assert settings.cache_ttl_seconds == 90.0


def test_radar_checkpoint_settings_expose_secret_bytes(monkeypatch):
    monkeypatch.setenv("RADAR_CHECKPOINT_SECRET", "super-secret")
    monkeypatch.setenv("SERVICE_ID", " radar-1 ")

    settings = get_radar_checkpoint_settings()

    assert settings.checkpoint_secret_bytes == b"super-secret"
    assert settings.SERVICE_ID == "radar-1"


def test_radar_checkpoint_settings_reject_empty_secret_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("RADAR_CHECKPOINT_SECRET", raising=False)

    with pytest.raises(
        ValidationError, match="RADAR_CHECKPOINT_SECRET must be set when ENVIRONMENT"
    ):
        get_radar_checkpoint_settings()


def test_radar_checkpoint_settings_allow_empty_secret_outside_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("RADAR_CHECKPOINT_SECRET", raising=False)

    settings = get_radar_checkpoint_settings()

    assert settings.checkpoint_secret_bytes == b""
