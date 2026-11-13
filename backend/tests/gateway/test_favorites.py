"""Members keep favorites of entities, readings and monitors."""

from unittest.mock import AsyncMock

import pytest
from off_key_api_gateway.api.rate_limiter import limiter
from off_key_api_gateway.providers import get_favorite_service
from off_key_core.schemas.favorites import FavoriteRef

from tests.support.gateway import gateway_app, member, returning
from tests.support.http import asgi_client

READING = {"kind": "reading", "id": "line/temperature"}
STORED = READING | {"created_at": "2026-11-05T00:00:00Z"}


@pytest.fixture
def favorites():
    service = AsyncMock()
    yield service
    limiter.reset()


async def call(favorites, method, path, body=None):
    # A plain member: favorites are not an administrator's privilege.
    app = gateway_app(
        member("user", id=7), overrides={get_favorite_service: returning(favorites)}
    )
    async with asgi_client(app) as client:
        return await client.request(method, path, json=body)


@pytest.mark.asyncio
async def test_a_member_lists_adds_and_removes_their_own_favorites(favorites):
    favorites.list_favorites.return_value = [STORED]
    favorites.add_favorite.return_value = STORED

    listed = await call(favorites, "GET", "/v1/favorites?kind=reading")
    added = await call(favorites, "POST", "/v1/favorites", READING)
    removed = await call(
        favorites, "DELETE", "/v1/favorites?kind=reading&id=line/temperature"
    )

    assert (listed.status_code, listed.json()) == (200, [STORED])
    assert (added.status_code, added.json()) == (200, STORED)
    assert (removed.status_code, removed.content) == (204, b"")
    ref = FavoriteRef.model_validate(READING)
    assert favorites.list_favorites.await_args.kwargs == {
        "user_id": 7,
        "kind": "reading",
    }
    assert favorites.add_favorite.await_args.kwargs == {"user_id": 7, "ref": ref}
    assert favorites.remove_favorite.await_args.kwargs == {"user_id": 7, "ref": ref}


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
async def test_malformed_favorites_are_refused_before_the_service_is_asked(
    favorites, method, path, body
):
    response = await call(favorites, method, path, body)

    assert response.status_code == 422
    assert favorites.mock_calls == []
