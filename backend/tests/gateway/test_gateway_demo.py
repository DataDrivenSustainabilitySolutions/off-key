"""The public demo: anonymous visitors read as the viewer member and change nothing."""

from unittest.mock import AsyncMock

import pytest
from fastapi.routing import iter_route_contexts
from off_key_api_gateway.api import demo
from off_key_api_gateway.app import build_app
from off_key_api_gateway.facades.tactic import TacticError
from off_key_api_gateway.settings import AppSettings, DemoSettings
from off_key_core.auth.tokens import decode_access_token
from pydantic import ValidationError

from tests.support.env import set_auth_env
from tests.support.http import asgi_client

VIEWER = {
    "id": 5,
    "email": "viewer@example.com",
    "role": "user",
    "session_version": 0,
}
SETTINGS = DemoSettings(
    DEMO_MODE=True,
    DEMO_VIEWER_EMAIL="viewer@example.com",
    DEMO_VIEWER_PASSWORD="viewer-password-123",
)


def demo_app(settings: DemoSettings = SETTINGS):
    return build_app(AppSettings(APP_NAME="off-key-test"), settings)


def guest_routes(app):
    for context in iter_route_contexts(app.router.routes):
        if context.path.startswith("/v1/") and not context.path.startswith(
            demo.OPEN_PREFIXES
        ):
            for method in context.methods or ():
                if method != "HEAD":
                    yield method, context.path


def concrete(path: str) -> str:
    return path.replace("{", "x").replace("}", "")


async def answer(method, endpoint, **_):
    if endpoint == "/api/v1/members/me":
        return VIEWER | {
            "is_active": True,
            "is_verified": True,
            "created_at": "2026-01-01T00:00:00Z",
        }
    return {"ok": True}


@pytest.fixture
def remote(monkeypatch):
    set_auth_env(monkeypatch)
    calls = AsyncMock(side_effect=answer)
    login = AsyncMock(return_value=VIEWER)
    monkeypatch.setattr(demo.tactic, "authenticate_user", login)
    monkeypatch.setattr(demo.tactic, "request", calls)
    return login, calls


def test_demo_mode_requires_a_viewer_account():
    with pytest.raises(ValidationError, match="DEMO_VIEWER_EMAIL"):
        DemoSettings(DEMO_MODE=True)
    assert DemoSettings().DEMO_MODE is False


def test_every_guest_route_exists_and_reads():
    routes = set(guest_routes(demo_app()))
    assert routes >= demo.GUEST_ROUTES
    writes = {
        (method, path)
        for method, path in demo.GUEST_ROUTES
        if method != "GET" and path != "/v1/system/collection/status"
    }
    assert writes == set()
    assert ("GET", "/v1/members") not in demo.GUEST_ROUTES
    assert ("GET", "/v1/system/revisions") not in demo.GUEST_ROUTES


@pytest.mark.asyncio
async def test_unlisted_routes_refuse_guests_before_any_remote_call(remote):
    login, calls = remote
    app = demo_app()
    refused = sorted(set(guest_routes(app)) - demo.GUEST_ROUTES)
    assert ("POST", "/v1/monitors/start") in refused
    async with asgi_client(app) as client:
        for method, path in refused:
            response = await client.request(method, concrete(path), json={})
            assert response.status_code == 403, (method, path)
            assert response.json() == {"detail": demo.READ_ONLY}
    login.assert_not_awaited()
    calls.assert_not_awaited()


@pytest.mark.asyncio
async def test_guest_reads_carry_the_viewer_token(remote):
    login, calls = remote
    async with asgi_client(demo_app()) as client:
        assert (await client.get("/v1/system")).status_code == 200
        assert (await client.get("/v1/system/health")).status_code == 200
    login.assert_awaited_once_with(
        email="viewer@example.com", password="viewer-password-123"
    )
    for call in calls.await_args_list:
        token = call.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        assert decode_access_token(token).user_id == 5


@pytest.mark.asyncio
async def test_signed_in_requests_and_sign_in_are_untouched(remote):
    login, calls = remote
    calls.side_effect = TacticError("Invalid token", status=401)
    async with asgi_client(demo_app()) as client:
        response = await client.post(
            "/v1/monitors/start", headers={"Authorization": "Bearer invalid"}
        )
        assert response.status_code == 401
        assert (await client.get("/v1/demo")).json() == {"enabled": True}
        assert (await client.get("/health")).status_code == 200
    login.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_administrator_viewer_is_refused(remote):
    login, calls = remote
    login.return_value = VIEWER | {"role": "admin"}
    async with asgi_client(demo_app()) as client:
        response = await client.get("/v1/system")
    assert response.status_code == 503
    calls.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_revoked_viewer_session_signs_in_again(remote):
    login, calls = remote
    revoked = [True]

    async def once_expired(method, endpoint, **kwargs):
        if revoked.pop() if revoked else False:
            raise TacticError("Expired", status=401)
        return await answer(method, endpoint, **kwargs)

    calls.side_effect = once_expired
    async with asgi_client(demo_app()) as client:
        assert (await client.get("/v1/system")).status_code == 401
        assert (await client.get("/v1/system")).status_code == 200
    assert login.await_count == 2


@pytest.mark.asyncio
async def test_guests_are_rate_limited_per_visitor(remote):
    settings = SETTINGS.model_copy(update={"DEMO_GUEST_REQUESTS_PER_MINUTE": 2})
    app = demo_app(settings)
    async with asgi_client(app, client=("203.0.113.7", 1)) as client:
        statuses = [(await client.get("/v1/system")).status_code for _ in range(3)]
    async with asgi_client(app, client=("203.0.113.8", 1)) as client:
        other = (await client.get("/v1/system")).status_code
    assert statuses == [200, 200, 429]
    assert other == 200


@pytest.mark.asyncio
async def test_without_demo_mode_anonymous_calls_still_need_sign_in(remote):
    login, _ = remote
    app = build_app(AppSettings(APP_NAME="off-key-test"), DemoSettings())
    async with asgi_client(app) as client:
        assert (await client.get("/v1/system")).status_code == 401
        assert (await client.get("/v1/demo")).json() == {"enabled": False}
    login.assert_not_awaited()
