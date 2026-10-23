"""Telemetry reads validate cursors and forward them to TACTIC in UTC."""

from unittest.mock import AsyncMock

import pytest
from off_key_api_gateway.api.rate_limiter import limiter
from off_key_api_gateway.facades import tactic as facade

from tests.support.gateway import gateway_app, member_profile
from tests.support.http import asgi_client


@pytest.fixture
def remote(monkeypatch):
    request = AsyncMock(return_value=[])
    monkeypatch.setattr(facade.tactic, "request", request)
    yield request
    limiter.reset()


async def get(path, **params):
    async with asgi_client(gateway_app(member_profile())) as client:
        return await client.get(f"/v1/telemetry/{path}", params=params)


@pytest.mark.asyncio
async def test_types_forward_the_limit_for_an_encoded_charger(remote):
    response = await get("site 1/type", limit=5)

    assert response.status_code == 200
    assert remote.await_args.kwargs == {
        "method": "GET",
        "endpoint": "/api/v1/data/telemetry/site%201/types",
        "params": {"limit": 5},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cursor", "forwarded"),
    [
        pytest.param({}, {}, id="first-page"),
        pytest.param(
            {"after_timestamp": "2026-01-01T02:00:00+02:00"},
            {"after_timestamp": "2026-01-01T00:00:00+00:00"},
            id="history",
        ),
        pytest.param(
            {
                "after_created": "2026-01-01T01:00:00+01:00",
                "after_event_timestamp": "2025-12-31T19:00:00-05:00",
            },
            {
                "after_created": "2026-01-01T00:00:00+00:00",
                "after_event_timestamp": "2026-01-01T00:00:00+00:00",
            },
            id="live",
        ),
    ],
)
async def test_data_cursors_are_forwarded_in_utc(remote, cursor, forwarded):
    response = await get("c1/data", type="L1", limit=50, paginated="true", **cursor)

    assert response.status_code == 200
    assert (
        remote.await_args.kwargs["params"]
        == {
            "type": "L1",
            "limit": 50,
            "paginated": True,
        }
        | forwarded
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cursor", "detail"),
    [
        (
            {"after_created": "2026-01-01T00:00:00Z"},
            "All telemetry live cursor fields are required",
        ),
        (
            {"after_event_timestamp": "2026-01-01T00:00:00Z"},
            "All telemetry live cursor fields are required",
        ),
        (
            {
                "after_timestamp": "2026-01-01T00:00:00Z",
                "after_created": "2026-01-01T00:00:00Z",
                "after_event_timestamp": "2026-01-01T00:00:00Z",
            },
            "Historical and live telemetry cursors cannot be used together",
        ),
    ],
)
async def test_inconsistent_cursors_are_rejected_before_tactic(remote, cursor, detail):
    response = await get("c1/data", type="L1", **cursor)

    assert response.status_code == 422
    assert response.json()["detail"] == detail
    remote.assert_not_awaited()
