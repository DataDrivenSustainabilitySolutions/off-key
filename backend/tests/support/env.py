"""Environment presets for tests that build settings from the process environment."""

from off_key_core.config.auth import get_auth_settings

AUTH_ENVIRONMENT = {
    "JWT_SECRET": "test-jwt-secret-key-material-123456",
    "ALGORITHM": "HS256",
    "ACCESS_TOKEN_EXPIRE_MINUTES": "30",
    "SUPERUSER_MAIL": "admin@example.com",
}

EMAIL_ENVIRONMENT = {
    "EMAIL_USERNAME": "sender@example.com",
    "EMAIL_PASSWORD": "email-secret",
    "EMAIL_FROM": "sender@example.com",
    "FRONTEND_BASE_URL": "http://localhost:5173",
    "SMTP_SERVER": "localhost",
    "SMTP_PORT": "1025",
    "MAIL_STARTTLS": "true",
    "MAIL_SSL_TLS": "false",
    "USE_CREDENTIALS": "true",
    "VALIDATE_CERTS": "false",
}


# Every service reads the database from these; none has defaults for them.
DATABASE_ENVIRONMENT = {
    "POSTGRES_USER": "postgres",
    "POSTGRES_PASSWORD": "postgres",
    "POSTGRES_HOST": "timescaledb",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "postgres",
}


def set_environment(monkeypatch, environment: dict[str, str]) -> None:
    for name, value in environment.items():
        monkeypatch.setenv(name, value)


def set_auth_env(monkeypatch) -> None:
    set_environment(monkeypatch, AUTH_ENVIRONMENT)
    get_auth_settings.cache_clear()
