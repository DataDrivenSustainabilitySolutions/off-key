"""Pin how TACTIC routers translate domain errors into HTTP responses."""

from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from off_key_core.db.base import get_db_async
from off_key_tactic_middleware.api import collection_auth
from off_key_tactic_middleware.api.v1 import data_services, members, pipelines, system
from off_key_tactic_middleware.domain import (
    AuthenticationError,
    ConflictError,
    DomainError,
    InfrastructureError,
    NotFoundError,
    ValidationError,
)
from off_key_tactic_middleware.provider import get_user_service
from off_key_tactic_middleware.services.pipelines.library import PipelineLibrary
from off_key_tactic_middleware.services.system_collection import (
    SystemCollectionService,
)

ERRORS = [
    (NotFoundError("missing"), 404, "missing"),
    (ConflictError("taken"), 409, "taken"),
    (AuthenticationError("denied"), 401, "denied"),
    (ValidationError("invalid"), 422, "invalid"),
    (InfrastructureError("db down"), 500, "Internal infrastructure error"),
    (DomainError("other"), 500, "Unexpected domain error"),
]
TOKEN = "a" * 43
ROUTES = {
    "data": ("POST", "/api/v1/data/auth/login", {"email": "a@b.c", "password": "x"}),
    "members": ("POST", "/api/v1/members/sessions/refresh", {"token": TOKEN}),
    "system": (
        "PUT",
        "/api/v1/system/collection",
        {
            "expected_revision": 0,
            "expected_collection_revision": 0,
            "stream_ids": ["stream-1"],
            "policy": {"mode": "sample", "interval_seconds": 2},
        },
    ),
    "pipelines": ("GET", "/api/v1/monitors/pipelines/p1", None),
}


def _app(error, nested, closed):
    async def fail(*args, **kwargs):
        raise error

    async def session():
        try:
            yield SimpleNamespace()
        except Exception:
            closed.append("rolled back")
            raise

    routers = [
        (data_services.router, "/api/v1/data"),
        (members.router, "/api/v1"),
        (system.router, "/api/v1"),
        (pipelines.router, "/api/v1"),
    ]
    app = FastAPI()
    if nested:
        parent = APIRouter()
        for router, prefix in routers:
            parent.include_router(router, prefix=prefix)
        app.include_router(parent)
    else:
        for router, prefix in routers:
            app.include_router(router, prefix=prefix)
    user = SimpleNamespace(email="admin@example.com", role="admin")
    app.dependency_overrides.update(
        {
            get_db_async: session,
            collection_auth.current_member: lambda: user,
            collection_auth.require_admin: lambda: user,
            get_user_service: lambda: SimpleNamespace(authenticate=fail),
            members.remembered_session_service: lambda: SimpleNamespace(refresh=fail),
        }
    )
    return app, fail


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("error,status,detail", ERRORS)
@pytest.mark.parametrize("route", ROUTES)
async def test_domain_errors_map_to_the_same_status_and_detail(
    monkeypatch, route, error, status, detail, nested
):
    closed = []
    app, fail = _app(error, nested, closed)
    monkeypatch.setattr(SystemCollectionService, "apply", fail)
    monkeypatch.setattr(PipelineLibrary, "get", fail)
    method, path, body = ROUTES[route]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, json=body)

    assert (response.status_code, response.json()) == (status, {"detail": detail})
    if route in {"system", "pipelines"}:
        assert closed == ["rolled back"]
