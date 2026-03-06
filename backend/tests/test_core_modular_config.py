from pathlib import Path

from off_key_core.config import (
    get_app_settings,
    get_auth_settings,
    get_database_settings,
    get_email_settings,
    get_runtime_settings,
    get_service_endpoints_settings,
    get_telemetry_settings,
    reset_runtime_caches_for_tests,
)
from off_key_core.clients.pionix import PionixClient
from off_key_core.clients.provider import get_charger_api_client
from off_key_core.config.database import DatabaseSettings
from off_key_core.config.validation import validate_settings
from off_key_core.db import base as db_base


def test_database_settings_parse_with_only_database_environment(monkeypatch):
    monkeypatch.setenv("POSTGRES_USER", "db_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "db_password")
    monkeypatch.setenv("POSTGRES_DB", "db_name")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("JWT_VERIFICATION_SECRET", raising=False)

    reset_runtime_caches_for_tests()

    database = get_database_settings()

    assert database.POSTGRES_USER == "db_user"
    assert database.POSTGRES_HOST == "localhost"
    assert database.database_url.endswith("@localhost:5432/db_name")

    reset_runtime_caches_for_tests()


def test_auth_settings_parse_with_only_auth_environment(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "super-secret-key-material-123456")
    monkeypatch.setenv("JWT_VERIFICATION_SECRET", "verify-secret-key-material-654321")
    monkeypatch.setenv("ALGORITHM", "HS256")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    monkeypatch.setenv("SUPERUSER_MAIL", "admin@example.com")
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    monkeypatch.delenv("POSTGRES_PORT", raising=False)
    monkeypatch.delenv("POSTGRES_HOST", raising=False)

    reset_runtime_caches_for_tests()

    auth = get_auth_settings()

    assert auth.ALGORITHM == "HS256"
    assert auth.ACCESS_TOKEN_EXPIRE_MINUTES == 30
    assert auth.SUPERUSER_MAIL == "admin@example.com"

    reset_runtime_caches_for_tests()


def test_email_settings_allow_default_alert_recipient(monkeypatch):
    monkeypatch.setenv("EMAIL_USERNAME", "sender@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "email-secret")
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")
    monkeypatch.setenv("FRONTEND_BASE_URL", "http://localhost:5173")
    monkeypatch.setenv("SMTP_SERVER", "localhost")
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.setenv("MAIL_STARTTLS", "true")
    monkeypatch.setenv("MAIL_SSL_TLS", "false")
    monkeypatch.setenv("USE_CREDENTIALS", "true")
    monkeypatch.setenv("VALIDATE_CERTS", "false")
    monkeypatch.delenv("ANOMALY_ALERT_RECIPIENTS", raising=False)

    reset_runtime_caches_for_tests()

    email = get_email_settings()

    assert email.anomaly_alert_recipients_list == ["admin@example.com"]

    reset_runtime_caches_for_tests()


def test_telemetry_settings_does_not_use_sync_alias(monkeypatch):
    monkeypatch.setenv("SYNC_RETENTION_DAYS", "21")
    monkeypatch.delenv("TELEMETRY_RETENTION_DAYS", raising=False)
    reset_runtime_caches_for_tests()

    telemetry = get_telemetry_settings()

    assert telemetry.retention_days == 14

    reset_runtime_caches_for_tests()


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


def test_db_engine_uses_runtime_debug_without_app_name(monkeypatch):
    monkeypatch.setenv("POSTGRES_USER", "db_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "db_password")
    monkeypatch.setenv("POSTGRES_DB", "db_name")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.delenv("APP_NAME", raising=False)

    reset_runtime_caches_for_tests()

    engine = db_base.get_engine()
    async_engine = db_base.get_async_engine()

    assert engine.echo is True
    assert async_engine.echo is True

    reset_runtime_caches_for_tests()


def test_client_provider_uses_runtime_default_without_app_name(monkeypatch):
    monkeypatch.setenv("PIONIX_KEY", "super-secret-pionix-key")
    monkeypatch.setenv("PIONIX_USER_AGENT", "off-key-tests")
    monkeypatch.delenv("CHARGER_API_PROVIDER", raising=False)
    monkeypatch.delenv("APP_NAME", raising=False)

    reset_runtime_caches_for_tests()

    runtime = get_runtime_settings()
    client = get_charger_api_client()

    assert runtime.CHARGER_API_PROVIDER == "pionix"
    assert isinstance(client, PionixClient)

    reset_runtime_caches_for_tests()


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


def test_gateway_validation_specs_no_longer_require_database(monkeypatch):
    monkeypatch.setenv("APP_NAME", "off-key")
    monkeypatch.setenv("JWT_SECRET", "super-secret-key-material-123456")
    monkeypatch.setenv("JWT_VERIFICATION_SECRET", "verify-secret-key-material-654321")
    monkeypatch.setenv("ALGORITHM", "HS256")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    monkeypatch.setenv("SUPERUSER_MAIL", "admin@example.com")
    monkeypatch.setenv("EMAIL_USERNAME", "sender@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "email-secret")
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")
    monkeypatch.setenv("FRONTEND_BASE_URL", "http://localhost:5173")
    monkeypatch.setenv("SMTP_SERVER", "localhost")
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.setenv("MAIL_STARTTLS", "true")
    monkeypatch.setenv("MAIL_SSL_TLS", "false")
    monkeypatch.setenv("USE_CREDENTIALS", "true")
    monkeypatch.setenv("VALIDATE_CERTS", "false")
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    monkeypatch.delenv("POSTGRES_PORT", raising=False)
    monkeypatch.delenv("POSTGRES_HOST", raising=False)

    reset_runtime_caches_for_tests()

    validate_settings(
        [
            ("app", get_app_settings),
            ("runtime", get_runtime_settings),
            ("auth", get_auth_settings),
            ("email", get_email_settings),
            ("services", get_service_endpoints_settings),
        ],
        context="API gateway configuration",
    )

    reset_runtime_caches_for_tests()


def test_gateway_main_validation_specs_exclude_database():
    project_root = Path(__file__).resolve().parents[1]
    gateway_main = (
        project_root
        / "services"
        / "api"
        / "gateway"
        / "src"
        / "off_key_api_gateway"
        / "main.py"
    )
    text = gateway_main.read_text(encoding="utf-8")

    assert '("runtime", get_runtime_settings)' in text
    assert '("database", get_database_settings)' not in text


def test_no_canonical_config_imports_or_get_settings_calls():
    project_root = Path(__file__).resolve().parents[1]
    roots = [
        project_root / "libs" / "core" / "src",
        project_root / "services",
        project_root / "tests",
    ]

    forbidden_module = "off_key_core.config." + "config"
    forbidden_get_settings = "get_" + "settings("

    violations: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if forbidden_module in text or forbidden_get_settings in text:
                violations.append(str(path.relative_to(project_root)))

    assert not violations, f"Found canonical config usage: {violations}"
