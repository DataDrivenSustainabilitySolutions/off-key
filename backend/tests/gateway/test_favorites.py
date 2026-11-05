"""Members keep favorites of entities, readings and monitors through the gateway."""

from unittest.mock import AsyncMock

import pytest
from off_key_api_gateway.api.rate_limiter import limiter
from off_key_api_gateway.facades import tactic as facade

from tests.support.gateway import gateway_app, member_profile
from tests.support.http import asgi_client

READING = {"kind": "reading", "id": "line/temperature"}
STORED = READING | {"created_at": "2026-11-05T00:00:00Z"}


@pytest.fixture
def downstream(monkeypatch):
    request = AsyncMock()
    monkeypatch.setattr(facade.tactic, "request", request)
    yield request
    limiter.reset()


async def call(method, path, body=None):
    # A plain member: favorites are not an administrator's privilege.
    async with asgi_client(gateway_app(member_profile("user", id=7))) as client:
        return await client.request(method, path, json=body)


@pytest.mark.asyncio
async def test_a_member_lists_adds_and_removes_their_own_favorites(downstream):
    downstream.side_effect = [[STORED], STORED, ""]

    listed = await call("GET", "/v1/favorites?kind=reading")
    added = await call("POST", "/v1/favorites", READING)
    removed = await call("DELETE", "/v1/favorites?kind=reading&id=line/temperature")

    assert (listed.status_code, listed.json()) == (200, [STORED])
    assert (added.status_code, added.json()) == (200, STORED)
    assert (removed.status_code, removed.content) == (204, b"")
    endpoint = "/api/v1/data/users/7/favorites"
    assert [call.kwargs for call in downstream.await_args_list] == [
        {"method": "GET", "endpoint": endpoint, "params": {"kind": "reading"}},
        {"method": "POST", "endpoint": endpoint, "json_data": READING},
        {"method": "DELETE", "endpoint": endpoint, "params": READING},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/v1/favorites?kind=charger", None),
        ("POST", "/v1/favorites", {"charger_id": "c1"}),
        ("POST", "/v1/favorites", {"kind": "monitor", "id": ""}),
        ("DELETE", "/v1/favorites?kind=reading", None),
    ],
)
async def test_malformed_favorites_are_rejected_before_forwarding(
    downstream, method, path, body
):
    response = await call(method, path, body)

    assert response.status_code == 422
    downstream.assert_not_awaited()
