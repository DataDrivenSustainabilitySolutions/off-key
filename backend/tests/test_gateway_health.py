import pytest

from tests.support.runtime_cache import reset_runtime_caches_for_tests

_GATEWAY_ENVIRONMENT = {
    "APP_NAME": "off-key-test",
    "DEBUG": "false",
    "JWT_SECRET": "test-signing-secret-material-123456789",
    "JWT_VERIFICATION_SECRET": "test-verification-secret-material-987654321",
    "ALGORITHM": "HS256",
    "ACCESS_TOKEN_EXPIRE_MINUTES": "30",
    "SUPERUSER_MAIL": "admin@example.com",
    "EMAIL_USERNAME": "sender@example.com",
    "EMAIL_PASSWORD": "test-email-password",
    "EMAIL_FROM": "sender@example.com",
    "FRONTEND_BASE_URL": "http://localhost:5173",
    "SMTP_SERVER": "localhost",
    "SMTP_PORT": "1025",
    "MAIL_STARTTLS": "true",
    "MAIL_SSL_TLS": "false",
    "USE_CREDENTIALS": "true",
    "VALIDATE_CERTS": "false",
    "ANOMALY_ALERT_RECIPIENTS": "admin@example.com",
}


@pytest.mark.asyncio
async def test_health_check_returns_liveness_payload(monkeypatch):
    for name, value in _GATEWAY_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)

    # The test must not inherit configuration from a developer's local .env.
    monkeypatch.setattr(
        "off_key_core.config.env.load_dotenv", lambda *args, **kwargs: False
    )
    reset_runtime_caches_for_tests()

    try:
        from off_key_api_gateway.main import health_check

        assert await health_check() == {"status": "healthy", "service": "api-gateway"}
    finally:
        reset_runtime_caches_for_tests()
