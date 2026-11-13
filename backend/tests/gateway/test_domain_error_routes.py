"""Pin how the API's routes translate domain errors into HTTP responses."""

from types import SimpleNamespace

import pytest
from off_key_api_gateway.providers import get_user_service
from off_key_core.db.base import get_db_async
from off_key_tactic_middleware.domain import (
    AuthenticationError,
    ConflictError,
    DomainError,
    InfrastructureError,
    NotFoundError,
    ValidationError,
)
from off_key_tactic_middleware.services.catalogue.system import SystemService
from off_key_tactic_middleware.services.pipelines.library import PipelineLibrary

from tests.support.gateway import gateway_app, member, returning
from tests.support.http import asgi_client

ERRORS = [
    (NotFoundError("missing"), 404, "missing"),
    (ConflictError("taken"), 409, "taken"),
    (AuthenticationError("denied"), 401, "denied"),
    (ValidationError("invalid"), 422, "invalid"),
    (InfrastructureError("db down"), 500, "Internal infrastructure error"),
    (DomainError("other"), 500, "Unexpected domain error"),
]
ROUTES = {
    "auth": ("POST", "/v1/auth/login", {"email": "a@b.c", "password": "x"}),
    "recording": (
        "PUT",
        "/v1/recording",
        {
            "expected_revision": 0,
            "expected_collection_revision": 0,
            "reading_ids": ["stream-1"],
            "policy": {"mode": "sample", "interval_seconds": 2},
        },
    ),
    "pipelines": ("GET", "/v1/pipelines/p1", None),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("error,status,detail", ERRORS)
@pytest.mark.parametrize("route", ROUTES)
async def test_domain_errors_map_to_the_same_status_and_detail(
    monkeypatch, route, error, status, detail
):
    closed = []

    async def fail(*args, **kwargs):
        raise error

    async def session():
        try:
            yield SimpleNamespace()
        except Exception:
            closed.append("rolled back")
            raise

    app = gateway_app(
        member("admin"),
        overrides={get_user_service: returning(SimpleNamespace(authenticate=fail))},
    )
    app.dependency_overrides[get_db_async] = session
    monkeypatch.setattr(SystemService, "apply_collection", fail)
    monkeypatch.setattr(PipelineLibrary, "get", fail)
    method, path, body = ROUTES[route]

    async with asgi_client(app) as client:
        response = await client.request(method, path, json=body)

    assert (response.status_code, response.json()) == (status, {"detail": detail})
    # A failed request never commits what it started.
    assert closed == ["rolled back"]
