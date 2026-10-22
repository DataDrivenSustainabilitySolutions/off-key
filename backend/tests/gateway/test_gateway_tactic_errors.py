from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status
from off_key_api_gateway.api.errors import (
    raise_tactic_http_error,
    tactic_error_detail,
)
from off_key_api_gateway.api.rate_limiter import limiter
from off_key_api_gateway.facades import tactic as facade
from off_key_api_gateway.facades.tactic import TacticError

from tests.support.gateway import gateway_app, member_profile
from tests.support.http import asgi_client


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
    # A TACTIC rate limit is forwarded, not answered by the gateway's limiter.
    (TacticError("busy", status=429, body={"detail": "busy"}), 429, "busy"),
]


@pytest.fixture
def gateway():
    yield gateway_app(member_profile("admin"))
    limiter.reset()


def _fail_downstream(monkeypatch, error):
    monkeypatch.setattr(facade.tactic, "request", AsyncMock(side_effect=error))


async def _call(app, method, path, body):
    async with asgi_client(app) as client:
        return await client.request(
            method, path, json=body, headers={"Authorization": "Bearer token"}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("error,status_code,detail", DOWNSTREAM_ERRORS)
@pytest.mark.parametrize("method,path,body", ROUTES)
async def test_downstream_failures_keep_status_and_detail(
    gateway, monkeypatch, method, path, body, error, status_code, detail
):
    _fail_downstream(monkeypatch, error)

    response = await _call(gateway, method, path, body)

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
    gateway, monkeypatch, method, path, body, upstream, detail
):
    error = TacticError("failed", status=upstream, body={"detail": "raw"})
    _fail_downstream(monkeypatch, error)

    response = await _call(gateway, method, path, body)

    expected = 409 if upstream == 400 else upstream
    assert (response.status_code, response.json()) == (expected, {"detail": detail})


@pytest.mark.asyncio
async def test_unsafe_pipeline_identifier_is_rejected_before_forwarding(
    gateway, monkeypatch
):
    _fail_downstream(monkeypatch, AssertionError("must not forward"))

    response = await _call(gateway, "GET", "/v1/monitors/pipelines/a%5Cb", None)

    assert (response.status_code, response.json()) == (
        422,
        {"detail": "Invalid resource identifier"},
    )
