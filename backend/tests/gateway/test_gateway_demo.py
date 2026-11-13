"""Exercise guest access through the real middleware, routing and permissions."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.routing import iter_route_contexts
from httpx import ASGITransport, AsyncClient
from off_key_api_gateway import providers
from off_key_api_gateway.api import access, demo
from off_key_api_gateway.app import build_app
from off_key_api_gateway.settings import AppSettings, DemoSettings
from off_key_core.auth.tokens import decode_access_token
from off_key_core.db.base import get_db_async
from off_key_core.schemas.dojo import DatasetListPage
from off_key_core.schemas.pipelines import PipelineProposalList
from off_key_core.schemas.system import SystemDocument, SystemSnapshot
from pydantic import ValidationError

from tests.support.env import set_auth_env
from tests.support.gateway import member, returning
from tests.support.http import asgi_client

VIEWER = dict(id=5, email="viewer@example.com", role="demo-viewer", session_version=0)
SETTINGS = DemoSettings(
    DEMO_MODE=True,
    DEMO_VIEWER_EMAIL="viewer@example.com",
    DEMO_VIEWER_PASSWORD="v" * 40,
)


PROPOSAL = dict(
    id="p1",
    name="Tram speed",
    reason="Flags stops between stations",
    author="private-admin@example.com",
    author_kind="member",
    status="accepted",
    test_run_id=None,
    replace_monitor_id=None,
    decided_by="private-admin@example.com",
    decided_at="2026-11-13T12:00:00Z",
    decision_note="Looks right",
    created_at="2026-11-13T11:00:00Z",
)


class Stores:
    """What the guest's reads reach, and who the API finds behind a token."""

    def __init__(self):
        self.system = AsyncMock()
        self.system.read.return_value = SystemSnapshot(
            revision=1,
            document=SystemDocument(),
            storage_origin="saved",
            updated_by="private-admin@example.com",
        )
        self.datasets = AsyncMock()
        self.datasets.list.return_value = DatasetListPage(items=[])
        self.proposals = AsyncMock()
        self.proposals.list.return_value = PipelineProposalList.model_validate(
            dict(
                items=[
                    PROPOSAL,
                    PROPOSAL | dict(id="p2", author_kind="agent", author="Scout"),
                ]
            )
        )
        self.permissions = ["use_dojo"]
        self.tokens: list[str] = []
        self.refuse = False

    async def signed_in_member(self, token, session):
        if self.refuse:
            raise HTTPException(401, "Invalid access token")
        self.tokens.append(token)
        claims = decode_access_token(token)
        return member(
            VIEWER["role"],
            permissions=self.permissions,
            id=claims.user_id,
            email=claims.sub,
        )

    def asked(self) -> list:
        return [
            *self.system.mock_calls,
            *self.datasets.mock_calls,
            *self.proposals.mock_calls,
        ]


@pytest.fixture
def stores(monkeypatch):
    set_auth_env(monkeypatch)
    stores = Stores()
    monkeypatch.setattr(access, "signed_in_member", stores.signed_in_member)
    return stores


@pytest.fixture
def login(monkeypatch):
    """The viewer's sign-in, against no database."""
    authenticate = AsyncMock(return_value=VIEWER)

    class Users:
        def __init__(self, session, repository):
            self.authenticate = authenticate

    @asynccontextmanager
    async def session():
        yield AsyncMock()

    monkeypatch.setattr(demo, "UserService", Users)
    monkeypatch.setattr(demo, "UserRepository", lambda session: None)
    monkeypatch.setattr(demo, "get_async_session_local", lambda: session)
    return authenticate


@pytest.fixture
def app(stores, login):
    def build(settings=SETTINGS):
        built = build_app(AppSettings(APP_NAME="test"), settings)
        built.dependency_overrides |= {
            get_db_async: returning(AsyncMock()),
            providers.get_system_service: returning(stores.system),
            providers.get_dojo_datasets: returning(stores.datasets),
            providers.get_pipeline_proposals: returning(stores.proposals),
        }
        return built

    return build


def routes():
    return {
        (method, route.path)
        for route in iter_route_contexts(
            build_app(AppSettings(APP_NAME="test"), SETTINGS).routes
        )
        if route.path.startswith("/v1/")
        and not route.path.startswith("/v1/auth/")
        and route.path != "/v1/demo"
        for method in route.methods or ()
        if method != "HEAD"
    }


def test_allowlist_tracks_real_routes_and_excludes_sensitive_reads():
    assert routes() >= demo.GUEST_ROUTES
    assert {item for item in demo.GUEST_ROUTES if item[0] != "GET"} == {
        ("POST", "/v1/recording/status"),
        ("POST", "/v1/alarms/query"),
    }
    assert {
        path for method, path in routes() - demo.GUEST_ROUTES if method == "GET"
    } == {
        "/v1/agents",
        "/v1/agents/me",
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
    app, stores, login
):
    async with asgi_client(app()) as client:
        for method, path in sorted(routes() - demo.GUEST_ROUTES):
            path = path.replace("{", "x").replace("}", "")
            response = await client.request(method, path, json={})
            assert response.status_code == 403, (method, path)
        assert (await client.get("/v1/future-sensitive-feature")).status_code == 403
    login.assert_not_awaited()
    assert stores.tokens == [] and stores.asked() == []


async def test_reads_use_server_only_credentials_and_redact_catalogue_author(
    app, stores, login
):
    async with asgi_client(app()) as client:
        response = await client.get("/v1/catalogue")
        assert response.status_code == 200
        assert response.json()["updated_by"] is None
        assert response.headers["cache-control"] == "no-store"
        assert "set-cookie" not in response.headers
        assert (await client.get("/v1/dojo/datasets")).status_code == 200
    login.assert_awaited_once()
    assert len(stores.tokens) == 2
    for token in stores.tokens:
        assert decode_access_token(token).user_id == 5
        assert token not in response.text


async def test_regular_installation_and_invalid_admin_tokens_do_not_become_guests(
    app, stores, login
):
    async with asgi_client(app(DemoSettings())) as client:
        assert (await client.get("/v1/catalogue")).status_code == 401
        assert not (await client.get("/v1/demo")).json()["enabled"]
    stores.refuse = True
    async with asgi_client(app()) as client:
        assert (
            await client.get(
                "/v1/catalogue", headers={"Authorization": "Bearer invalid"}
            )
        ).status_code == 401
    login.assert_not_awaited()
    assert stores.asked() == []


async def test_elevating_cached_viewer_permissions_closes_access_immediately(
    app, stores, login
):
    async with asgi_client(app()) as client:
        assert (await client.get("/v1/catalogue")).status_code == 200
        stores.permissions = ["use_dojo", "manage_sources"]
        assert (await client.get("/v1/catalogue")).status_code == 503
    login.assert_awaited_once()


async def test_admin_viewer_refused_and_failed_signin_has_backoff(app, login):
    login.return_value = VIEWER | {"role": "admin"}
    async with asgi_client(app()) as client:
        assert (await client.get("/v1/catalogue")).status_code == 503
        assert (await client.get("/v1/catalogue")).status_code == 503
        assert (await client.get("/v1/demo")).json()["enabled"]
    login.assert_awaited_once()


async def test_guest_budgets_are_per_address(app):
    demo_app = app(SETTINGS.model_copy(update={"DEMO_GUEST_REQUESTS_PER_MINUTE": 2}))
    async with asgi_client(demo_app, client=("203.0.113.7", 1)) as client:
        assert [(await client.get("/v1/catalogue")).status_code for _ in range(3)] == [
            200,
            200,
            429,
        ]
    async with asgi_client(demo_app, client=("203.0.113.8", 1)) as client:
        assert (await client.get("/v1/catalogue")).status_code == 200


async def test_guests_read_proposals_with_agents_named_and_members_hidden(app):
    async with asgi_client(app()) as client:
        response = await client.get("/v1/pipeline-proposals")
    assert response.status_code == 200
    assert "private-admin@example.com" not in response.text
    by_member, by_agent = response.json()["items"]
    assert (by_member["author"], by_member["decided_by"]) == ("A member", "A member")
    assert (by_agent["author"], by_agent["decided_by"]) == ("Scout", "A member")
    assert by_member["reason"] == "Flags stops between stations"


async def test_guests_are_recognised_behind_the_deployed_api_root_path(app):
    # Uvicorn runs with --root-path /api and passes the full path, prefix included.
    transport = ASGITransport(app=app(), root_path="/api")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/catalogue")
        assert response.status_code == 200
        assert response.json()["updated_by"] is None
        assert (await client.put("/api/v1/catalogue", json={})).status_code == 403
