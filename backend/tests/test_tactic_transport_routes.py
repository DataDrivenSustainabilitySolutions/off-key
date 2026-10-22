"""Payloads of routes whose logic moved from routers into services."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from off_key_core.db.base import get_db_async
from off_key_core.db.models import MonitoringService
from off_key_core.utils.enum import RoleEnum
from off_key_tactic_middleware.api.collection_auth import current_member
from off_key_tactic_middleware.api.v1 import pipelines as pipelines_api
from off_key_tactic_middleware.api.v1 import system as system_api
from off_key_tactic_middleware.provider import get_radar_orchestration_service


def client(router, session, overrides=None):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db_async] = lambda: session
    app.dependency_overrides[current_member] = lambda: SimpleNamespace(
        id=1, email="member@example.com", role=RoleEnum.user
    )
    for dependency, value in (overrides or {}).items():
        app.dependency_overrides[dependency] = value
    return TestClient(app)


def service_session(services):
    session = AsyncMock()

    async def get(model, identifier, **_):
        assert model is MonitoringService
        return services.get(identifier)

    session.get.side_effect = get
    return session


def monitor(state):
    return SimpleNamespace(operational_status={"pipeline_state": state})


def test_pipeline_state_returns_the_stored_state_or_a_404():
    session = service_session({"m1": monitor({"nodes": 3}), "m2": monitor(None)})
    with client(pipelines_api.router, session) as http:
        assert http.get("/monitors/m1/pipeline-state").json() == {"nodes": 3}
        assert http.get("/monitors/m2/pipeline-state").json() is None
        missing = http.get("/monitors/unknown/pipeline-state")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Monitoring service not found"}


def test_workspace_reports_the_selected_service_state_and_tolerates_unknowns():
    session = service_session({"m1": monitor({"nodes": 3})})
    orchestration = SimpleNamespace(list_radar_services=AsyncMock(return_value=[]))
    overrides = {get_radar_orchestration_service: lambda: orchestration}
    with client(pipelines_api.router, session, overrides) as http:
        selected = http.get("/monitors/workspace", params={"selected_service_id": "m1"})
        unknown = http.get("/monitors/workspace", params={"selected_service_id": "x"})
        none = http.get("/monitors/workspace")
    assert selected.json()["pipeline_state"] == {"nodes": 3}
    assert selected.json()["selected_service_id"] == "m1"
    assert unknown.json()["pipeline_state"] is None
    assert none.json()["pipeline_state"] is None
    orchestration.list_radar_services.assert_awaited_with(include_docker_status=False)


def test_system_revisions_are_newest_first_with_isoformat_times():
    rows = [
        SimpleNamespace(
            revision=revision,
            updated_at=datetime(2026, 10, revision, tzinfo=UTC),
            updated_by="admin@example.com",
        )
        for revision in (2, 1)
    ]
    session = AsyncMock()
    session.scalars.return_value = rows
    with client(system_api.router, session) as http:
        response = http.get("/system/revisions")
    assert response.json() == [
        {
            "revision": 2,
            "updated_at": "2026-10-02T00:00:00+00:00",
            "updated_by": "admin@example.com",
        },
        {
            "revision": 1,
            "updated_at": "2026-10-01T00:00:00+00:00",
            "updated_by": "admin@example.com",
        },
    ]
    query = str(session.scalars.call_args.args[0])
    assert "ORDER BY system_revisions.revision DESC" in query
    assert "LIMIT" in query
