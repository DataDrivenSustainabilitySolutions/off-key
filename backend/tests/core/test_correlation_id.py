"""One correlation ID per request, bound before any middleware logs."""

import uuid

import pytest
from fastapi import FastAPI, Response
from httpx import ASGITransport, AsyncClient
from off_key_core.config.logging import get_logging_settings
from off_key_core.config.logs import (
    CorrelationIdMiddleware,
    correlation_headers,
    get_correlation_id,
)
from off_key_tactic_middleware.main import create_app
from starlette.middleware.base import BaseHTTPMiddleware


@pytest.fixture(autouse=True)
def header(monkeypatch):
    monkeypatch.setenv("LOG_CORRELATION_HEADER", "X-Correlation-ID")
    get_logging_settings.cache_clear()
    yield
    get_logging_settings.cache_clear()


def _app() -> tuple[FastAPI, list]:
    seen = []
    app = FastAPI()

    @app.get("/")
    async def respond(status: int = 200):
        seen.append(("endpoint", get_correlation_id()))
        return Response(status_code=status)

    class Inner(BaseHTTPMiddleware):
        # Stands in for the gateway's security log, which runs after the response.
        async def dispatch(self, request, call_next):
            response = await call_next(request)
            seen.append(("inner", get_correlation_id()))
            return response

    app.add_middleware(Inner)
    app.add_middleware(CorrelationIdMiddleware)
    return app, seen


async def _get(app, headers=None, url="/"):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(url, headers=headers)


async def test_valid_inbound_id_is_kept_through_inner_middleware():
    app, seen = _app()

    response = await _get(app, {"X-Correlation-ID": "request-123"}, "/?status=401")

    assert response.headers["X-Correlation-ID"] == "request-123"
    assert seen == [("endpoint", "request-123"), ("inner", "request-123")]
    assert get_correlation_id() is None


@pytest.mark.parametrize("inbound", [None, "", "two words", "x" * 129, "id\nforged"])
async def test_missing_or_unsafe_ids_are_replaced(inbound):
    app, seen = _app()

    response = await _get(
        app, None if inbound is None else {"X-Correlation-ID": inbound}
    )

    assigned = response.headers["X-Correlation-ID"]
    assert assigned != inbound
    assert uuid.UUID(assigned)
    assert seen == [("endpoint", assigned), ("inner", assigned)]


def test_correlation_headers_forward_only_a_bound_id():
    assert correlation_headers() == {}


async def test_downstream_calls_see_the_request_id():
    app = FastAPI()

    @app.get("/")
    async def respond():
        return correlation_headers()

    app.add_middleware(CorrelationIdMiddleware)
    response = await _get(app, {"X-Correlation-ID": "request-123"})

    assert response.json() == {"X-Correlation-ID": "request-123"}


def test_tactic_binds_the_id_outermost():
    app = create_app()

    assert app.user_middleware[0].cls is CorrelationIdMiddleware
