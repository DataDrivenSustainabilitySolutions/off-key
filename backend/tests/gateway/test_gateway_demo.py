"""Exercise guest access through the real middleware, routing and permissions."""

from unittest.mock import AsyncMock

import pytest
from fastapi.routing import iter_route_contexts
from off_key_api_gateway.api import demo
from off_key_api_gateway.app import build_app
from off_key_api_gateway.facades.tactic import TacticError
from off_key_api_gateway.settings import AppSettings, DemoSettings
from off_key_core.auth.tokens import decode_access_token
from off_key_core.schemas.system import SystemDocument
from pydantic import ValidationError

from tests.support.env import set_auth_env
from tests.support.http import asgi_client

VIEWER = dict(id=5, email="viewer@example.com", role="demo-viewer", session_version=0)
SETTINGS = DemoSettings(
    DEMO_MODE=True,
    DEMO_VIEWER_EMAIL="viewer@example.com",
    DEMO_VIEWER_PASSWORD="v" * 40,
)


def app(settings=SETTINGS):
    return build_app(AppSettings(APP_NAME="test"), settings)


def routes():
    return {
        (method, route.path)
        for route in iter_route_contexts(app().routes)
        if route.path.startswith("/v1/")
        and not route.path.startswith("/v1/auth/")
        and route.path != "/v1/demo"
        for method in route.methods or ()
        if method != "HEAD"
    }


async def answer(method, path, **kwargs):
    if path == "/api/v1/members/me":
        return VIEWER | dict(
            permissions=["use_dojo"],
            is_active=True,
            is_verified=True,
            created_at="2026-01-01T00:00:00Z",
        )
    if path == "/api/v1/system":
        return dict(
            revision=1,
            document=SystemDocument().model_dump(),
            runtime={},
            can_edit=False,
            updated_by="private-admin@example.com",
        )
    if path == "/api/v1/dojo/datasets":
        return dict(items=[], next_offset=None)
    return {}


@pytest.fixture
def remote(monkeypatch):
    set_auth_env(monkeypatch)
    calls, login = AsyncMock(side_effect=answer), AsyncMock(return_value=VIEWER)
    monkeypatch.setattr(demo.tactic, "request", calls)
    monkeypatch.setattr(demo.tactic, "authenticate_user", login)
    return login, calls


def test_allowlist_tracks_real_routes_and_excludes_sensitive_reads():
    assert routes() >= demo.GUEST_ROUTES
    assert {item for item in demo.GUEST_ROUTES if item[0] != "GET"} == {
        ("POST", "/v1/recording/status"),
        ("POST", "/v1/alarms/query"),
    }
    assert {
        path for method, path in routes() - demo.GUEST_ROUTES if method == "GET"
    } == {
        "/v1/me",
        "/v1/members",
        "/v1/roles",
        "/v1/permissions",
        "/v1/favorites",
        "/v1/catalogue/revisions",
        "/v1/live/measurements",
        "/v1/dojo/datasets/{dataset_id}/label-suggestions",
    }


def test_explicit_demo_configuration_is_required():
    assert not DemoSettings().DEMO_MODE
    with pytest.raises(ValidationError, match="DEMO_VIEWER_EMAIL"):
        DemoSettings(DEMO_MODE=True)


async def test_every_unlisted_route_and_mutation_is_closed_before_authentication(
    remote,
):
    login, calls = remote
    async with asgi_client(app()) as client:
        for method, path in sorted(routes() - demo.GUEST_ROUTES):
            path = path.replace("{", "x").replace("}", "")
            response = await client.request(method, path, json={})
            assert response.status_code == 403, (method, path)
        assert (await client.get("/v1/future-sensitive-feature")).status_code == 403
    login.assert_not_awaited()
    calls.assert_not_awaited()


async def test_reads_use_server_only_credentials_and_redact_catalogue_author(remote):
    login, calls = remote
    async with asgi_client(app()) as client:
        response = await client.get("/v1/catalogue")
        assert response.status_code == 200
        assert response.json()["updated_by"] is None
        assert response.headers["cache-control"] == "no-store"
        assert "set-cookie" not in response.headers
        assert (await client.get("/v1/dojo/datasets")).status_code == 200
    login.assert_awaited_once()
    for call in calls.await_args_list:
        token = call.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        assert decode_access_token(token).user_id == 5
        assert token not in response.text


async def test_regular_installation_and_invalid_admin_tokens_do_not_become_guests(
    remote,
):
    login, calls = remote
    async with asgi_client(app(DemoSettings())) as client:
        assert (await client.get("/v1/catalogue")).status_code == 401
        assert not (await client.get("/v1/demo")).json()["enabled"]
    calls.side_effect = TacticError("Invalid", status=401)
    async with asgi_client(app()) as client:
        assert (
            await client.get(
                "/v1/catalogue", headers={"Authorization": "Bearer invalid"}
            )
        ).status_code == 401
    login.assert_not_awaited()


async def test_elevating_cached_viewer_permissions_closes_access_immediately(remote):
    login, calls = remote
    async with asgi_client(app()) as client:
        assert (await client.get("/v1/catalogue")).status_code == 200
        calls.side_effect = None
        calls.return_value = await answer("GET", "/api/v1/members/me") | {
            "permissions": ["use_dojo", "manage_sources"]
        }
        assert (await client.get("/v1/catalogue")).status_code == 503
    login.assert_awaited_once()


async def test_admin_viewer_refused_and_failed_signin_has_backoff(remote):
    login, _ = remote
    login.return_value = VIEWER | {"role": "admin"}
    async with asgi_client(app()) as client:
        assert (await client.get("/v1/catalogue")).status_code == 503
        assert (await client.get("/v1/catalogue")).status_code == 503
        assert (await client.get("/v1/demo")).json()["enabled"]
    login.assert_awaited_once()


async def test_guest_budgets_are_per_address(remote):
    demo_app = app(SETTINGS.model_copy(update={"DEMO_GUEST_REQUESTS_PER_MINUTE": 2}))
    async with asgi_client(demo_app, client=("203.0.113.7", 1)) as client:
        assert [(await client.get("/v1/catalogue")).status_code for _ in range(3)] == [
            200,
            200,
            429,
        ]
    async with asgi_client(demo_app, client=("203.0.113.8", 1)) as client:
        assert (await client.get("/v1/catalogue")).status_code == 200
