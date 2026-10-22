from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient
from off_key_api_gateway.api import access
from off_key_api_gateway.api.errors import (
    raise_tactic_http_error,
    tactic_error_detail,
)
from off_key_api_gateway.api.rate_limiter import limiter, rate_limit_exceeded_handler
from off_key_api_gateway.api.v1 import routes
from off_key_api_gateway.facades import tactic as facade
from off_key_api_gateway.facades.tactic import TacticError
from off_key_core.schemas.members import MemberProfile


def test_tactic_error_detail_prefers_downstream_api_detail():
    error = TacticError(
        "downstream request failed",
        status=status.HTTP_409_CONFLICT,
        body={"detail": "sensor is already claimed"},
    )

    assert tactic_error_detail(error) == "sensor is already claimed"


def test_raise_tactic_http_error_preserves_status_and_cause():
    error = TacticError(
        "downstream request failed",
        status=status.HTTP_404_NOT_FOUND,
        body={"detail": "service not found"},
    )

    with pytest.raises(HTTPException) as exc_info:
        raise_tactic_http_error(error)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "service not found"
    assert exc_info.value.__cause__ is error


def test_raise_tactic_http_error_defaults_to_bad_gateway():
    error = TacticError("connection failed")

    with pytest.raises(HTTPException) as exc_info:
        raise_tactic_http_error(error)

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert exc_info.value.detail == "connection failed"


ROUTES = [
    ("GET", "/v1/chargers/available", None),
    ("GET", "/v1/telemetry/c1/type", None),
    ("GET", "/v1/anomalies/count", None),
    ("GET", "/v1/favorites", None),
    ("GET", "/v1/members", None),
    ("GET", "/v1/system", None),
    ("PATCH", "/v1/monitors/svc-1/label", {"display_name": "Pump"}),
    ("GET", "/v1/monitors/pipelines/p1", None),
    (
        "POST",
        "/v1/auth/reset-password",
        {"token": "t" * 43, "new_password": "Correct-Horse-9-Battery"},
    ),
]
DOWNSTREAM_ERRORS = [
    (TacticError("failed", status=409, body={"detail": "claimed"}), 409, "claimed"),
    (TacticError("tactic unreachable"), 502, "tactic unreachable"),
]


@pytest.fixture
def gateway_app():
    app = FastAPI()
    app.include_router(routes.router, prefix="/v1")
    app.state.limiter = limiter
    app.add_exception_handler(429, rate_limit_exceeded_handler)
    member = MemberProfile(
        id=17,
        email="admin@example.com",
        role="admin",
        is_active=True,
        is_verified=True,
        created_at=datetime.now(UTC),
    )
    app.dependency_overrides[access.current_member] = lambda: member
    limiter.reset()
    yield app
    limiter.reset()


def _fail_downstream(monkeypatch, error):
    monkeypatch.setattr(facade.tactic, "request", AsyncMock(side_effect=error))


async def _call(app, method, path, body):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.request(
            method, path, json=body, headers={"Authorization": "Bearer token"}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("error,status_code,detail", DOWNSTREAM_ERRORS)
@pytest.mark.parametrize("method,path,body", ROUTES)
async def test_downstream_failures_keep_status_and_detail(
    gateway_app, monkeypatch, method, path, body, error, status_code, detail
):
    _fail_downstream(monkeypatch, error)

    response = await _call(gateway_app, method, path, body)

    assert (response.status_code, response.json()) == (
        status_code,
        {"detail": detail},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,body,upstream,detail",
    [
        (
            "POST",
            "/v1/favorites",
            {"charger_id": "c1"},
            400,
            "Charger already favorited",
        ),
        (
            "POST",
            "/v1/favorites",
            {"charger_id": "c1"},
            409,
            "Charger already favorited",
        ),
        ("DELETE", "/v1/favorites", {"charger_id": "c1"}, 404, "Favorite not found"),
        ("DELETE", "/v1/anomalies/a1", None, 404, "Anomaly not found"),
    ],
)
async def test_gateway_rewords_some_downstream_failures(
    gateway_app, monkeypatch, method, path, body, upstream, detail
):
    error = TacticError("failed", status=upstream, body={"detail": "raw"})
    _fail_downstream(monkeypatch, error)

    response = await _call(gateway_app, method, path, body)

    expected = 409 if upstream == 400 else upstream
    assert (response.status_code, response.json()) == (expected, {"detail": detail})


@pytest.mark.asyncio
async def test_unsafe_pipeline_identifier_is_rejected_before_forwarding(
    gateway_app, monkeypatch
):
    _fail_downstream(monkeypatch, AssertionError("must not forward"))

    response = await _call(gateway_app, "GET", "/v1/monitors/pipelines/a%5Cb", None)

    assert (response.status_code, response.json()) == (
        422,
        {"detail": "Invalid resource identifier"},
    )
