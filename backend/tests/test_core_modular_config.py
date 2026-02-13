from off_key_core.config import (
    get_database_settings,
    reset_runtime_caches_for_tests,
    get_service_endpoints_settings,
    get_telemetry_settings,
)
from off_key_core.config.config import get_settings
from off_key_core.config.database import DatabaseSettings
from off_key_core.db import base as db_base


def test_modular_database_settings_match_canonical_settings():
    reset_runtime_caches_for_tests()

    canonical = get_settings()
    database = get_database_settings()

    assert database.POSTGRES_USER == canonical.POSTGRES_USER
    assert database.POSTGRES_HOST == canonical.POSTGRES_HOST
    assert database.database_url == canonical.database_url
    assert database.async_database_url == canonical.async_database_url


def test_telemetry_settings_uses_canonical_alias(monkeypatch):
    monkeypatch.setenv("SYNC_RETENTION_DAYS", "21")
    monkeypatch.delenv("TELEMETRY_RETENTION_DAYS", raising=False)
    reset_runtime_caches_for_tests()

    telemetry = get_telemetry_settings()

    assert telemetry.retention_days == 21

    reset_runtime_caches_for_tests()


def test_modular_service_settings_match_canonical_settings():
    reset_runtime_caches_for_tests()

    canonical = get_settings()
    service_endpoints = get_service_endpoints_settings()

    assert service_endpoints.SYNC_SERVICE_SCHEME == canonical.SYNC_SERVICE_SCHEME
    assert service_endpoints.TACTIC_SERVICE_SCHEME == canonical.TACTIC_SERVICE_SCHEME
    assert service_endpoints.db_sync_service_url == canonical.db_sync_service_url
    assert (
        service_endpoints.tactic_service_base_url == canonical.tactic_service_base_url
    )


def test_modular_service_settings_support_https_overrides(monkeypatch):
    monkeypatch.setenv("SYNC_SERVICE_SCHEME", "HTTPS")
    monkeypatch.setenv("TACTIC_SERVICE_SCHEME", "https")
    reset_runtime_caches_for_tests()

    service_endpoints = get_service_endpoints_settings()

    assert service_endpoints.SYNC_SERVICE_SCHEME == "https"
    assert service_endpoints.TACTIC_SERVICE_SCHEME == "https"
    assert service_endpoints.db_sync_service_url.startswith("https://")
    assert service_endpoints.tactic_service_base_url.startswith("https://")

    reset_runtime_caches_for_tests()


def test_db_engine_is_lazily_cached():
    reset_runtime_caches_for_tests()

    assert db_base.get_engine.cache_info().currsize == 0
    assert db_base.get_async_engine.cache_info().currsize == 0

    db_base.get_engine()
    db_base.get_async_engine()

    assert db_base.get_engine.cache_info().currsize == 1
    assert db_base.get_async_engine.cache_info().currsize == 1

    reset_runtime_caches_for_tests()

    assert db_base.get_engine.cache_info().currsize == 0
    assert db_base.get_async_engine.cache_info().currsize == 0


def test_database_url_encodes_reserved_credential_characters():
    settings = DatabaseSettings(
        POSTGRES_USER="user@name",
        POSTGRES_PASSWORD="p@ss:word/?#[]",
        POSTGRES_DB="db",
        POSTGRES_PORT="5432",
        POSTGRES_HOST="localhost",
    )

    assert (
        settings.database_url
        == "postgresql://user%40name:p%40ss%3Aword%2F%3F%23%5B%5D@localhost:5432/db"
    )
    assert (
        settings.async_database_url
        == "postgresql+asyncpg://user%40name:p%40ss%3Aword%2F%3F%23%5B%5D"
        "@localhost:5432/db"
    )
