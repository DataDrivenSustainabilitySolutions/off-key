import pytest


@pytest.mark.asyncio
async def test_health_check_returns_liveness_payload(monkeypatch):
    monkeypatch.setenv("DEBUG", "false")

    from off_key_api_gateway.main import health_check

    assert await health_check() == {"status": "healthy", "service": "api-gateway"}
