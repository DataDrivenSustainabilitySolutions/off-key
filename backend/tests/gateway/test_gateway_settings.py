"""Gateway-only settings: service endpoints the gateway calls."""

from off_key_api_gateway.settings import get_service_endpoints_settings


def test_service_endpoints_support_https_overrides(monkeypatch):
    monkeypatch.setenv("TACTIC_SERVICE_SCHEME", "HTTPS")
    service_endpoints = get_service_endpoints_settings()

    assert service_endpoints.TACTIC_SERVICE_SCHEME == "https"
    assert service_endpoints.TACTIC_SERVICE_REQUEST_TIMEOUT_SECONDS == 180.0
    assert service_endpoints.tactic_service_base_url.startswith("https://")


def test_service_endpoints_support_tactic_timeout_override(monkeypatch):
    monkeypatch.setenv("TACTIC_SERVICE_REQUEST_TIMEOUT_SECONDS", "45.5")
    service_endpoints = get_service_endpoints_settings()

    assert service_endpoints.TACTIC_SERVICE_REQUEST_TIMEOUT_SECONDS == 45.5
