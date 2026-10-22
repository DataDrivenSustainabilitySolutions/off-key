import pytest

from tests.support.env import AUTH_ENVIRONMENT, EMAIL_ENVIRONMENT, set_environment
from tests.support.runtime_cache import reset_runtime_caches_for_tests

_GATEWAY_ENVIRONMENT = {
    **AUTH_ENVIRONMENT,
    **EMAIL_ENVIRONMENT,
    "INTERNAL_API_SECRET": "test-internal-service-secret-123456789",
    "APP_NAME": "off-key-test",
    "DEBUG": "false",
    "ANOMALY_ALERT_RECIPIENTS": "admin@example.com",
}


@pytest.mark.asyncio
async def test_health_check_returns_liveness_payload(monkeypatch):
    set_environment(monkeypatch, _GATEWAY_ENVIRONMENT)

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
