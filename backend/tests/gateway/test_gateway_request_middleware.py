"""Gateway request logging: redacted request logs and security events."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from off_key_api_gateway.api import middleware
from off_key_core.config.logging import get_logging_settings

from tests.support.http import asgi_client


@pytest.fixture
def log(monkeypatch):
    monkeypatch.setenv("LOG_REDACT_PII", "true")
    monkeypatch.setenv("LOG_CORRELATION_HEADER", "X-Correlation-ID")
    monkeypatch.setenv("ENABLE_REQUEST_LOGGING", "true")
    monkeypatch.setenv("ENABLE_PERFORMANCE_LOGGING", "true")
    get_logging_settings.cache_clear()
    log = MagicMock()
    monkeypatch.setattr(middleware, "logger", log)
    monkeypatch.setattr(middleware, "log_performance", MagicMock())
    yield log
    get_logging_settings.cache_clear()


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/{path:path}")
    async def respond(path: str, status: int = 200):
        if status == 500:
            raise RuntimeError("downstream failed")
        if status != 200:
            raise HTTPException(status_code=status)
        return {"path": path}

    app.add_middleware(middleware.RequestLoggingMiddleware)
    return app


async def _get(app: FastAPI, url: str, headers=None):
    async with asgi_client(app) as client:
        return await client.get(url, headers=headers)


async def test_request_log_records_performance_for_each_request(log):
    app = _app()

    await _get(app, "/items")
    await _get(app, "/items")

    assert middleware.log_performance.call_count == 2


async def test_request_log_redacts_secrets_and_truncates_user_agents(log):
    app = _app()

    await _get(
        app,
        "/items?token=top-secret-value&page=2",
        {"user-agent": "u" * 200},
    )

    _, method, path, status, _, query, user_agent = log.info.call_args.args
    assert (method, path, status) == ("GET", "/items", 200)
    assert query["page"] == "2"
    assert "top-secret-value" not in str(query)
    assert user_agent == "u" * 117 + "..."


async def test_request_log_records_and_reraises_downstream_failures(log):
    with pytest.raises(RuntimeError, match="downstream failed"):
        await _get(_app(), "/items?status=500")

    message, method, path, *_, error = log.exception.call_args.args
    assert message.startswith("event=http.request_failed")
    assert (method, path, error) == ("GET", "/items", "downstream failed")


@pytest.mark.parametrize(
    ("url", "events"),
    [
        ("/items", []),
        ("/.env", ["suspicious_request"]),
        ("/items/../../etc/passwd", ["suspicious_request"]),
        ("/items?status=401", ["authentication_failed"]),
        ("/items?status=403", ["authorization_failed"]),
        ("/admin?status=401", ["suspicious_request", "authentication_failed"]),
    ],
)
async def test_security_log_flags_probing_paths_and_auth_failures(log, url, events):
    await _get(_app(), url)

    logged = [call.args[0].split()[0] for call in log.warning.call_args_list]
    assert logged == [f"event=security.{event}" for event in events]
    for call in log.warning.call_args_list:
        assert "127.0.0.1" not in call.args
        assert "127.0.0.x" in call.args
