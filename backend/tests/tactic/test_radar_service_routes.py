"""TACTIC's RADAR service routes validate lookups and map outcomes to HTTP."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from off_key_core.db.maintenance import DeploymentInProgressError
from off_key_tactic_middleware.api.v1 import radar
from off_key_tactic_middleware.provider import get_radar_orchestration_service

from tests.support.http import asgi_client

BY_NAME = {"container_name": "radar-1"}
BY_ID = {"container_id": "abc"}


def orchestration(**methods):
    service = AsyncMock()
    for name, outcome in methods.items():
        setattr(
            service,
            name,
            AsyncMock(
                side_effect=outcome if isinstance(outcome, Exception) else None,
                return_value=outcome,
            ),
        )
    return service


async def call(service, method, path, params=None, body=None):
    app = FastAPI()
    app.include_router(radar.router)
    app.dependency_overrides[get_radar_orchestration_service] = lambda: service
    async with asgi_client(app) as client:
        return await client.request(method, path, params=params, json=body)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/radar/services/details/"), ("DELETE", "/radar/services/stop/")],
)
@pytest.mark.parametrize(
    ("params", "detail"),
    [
        ({}, "You must provide either container_name or container_id."),
        (BY_NAME | BY_ID, "Provide only one of container_name or container_id."),
    ],
)
async def test_lookups_need_exactly_one_identifier(method, path, params, detail):
    service = orchestration()
    response = await call(service, method, path, params)

    assert (response.status_code, response.json()["detail"]) == (400, detail)
    assert service.method_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "params", "operation", "outcome", "status"),
    [
        ("GET", "/radar/services/details/", BY_ID, "get_radar_service", {"id": 1}, 200),
        ("GET", "/radar/services/details/", BY_ID, "get_radar_service", None, 404),
        ("DELETE", "/radar/services/stop/", BY_NAME, "stop_radar_service", True, 200),
        ("DELETE", "/radar/services/stop/", BY_NAME, "stop_radar_service", False, 404),
        ("DELETE", "/radar/services/s1", None, "delete_radar_service", True, 200),
        ("DELETE", "/radar/services/s1", None, "delete_radar_service", False, 404),
        ("GET", "/radar/services/", None, "list_radar_services", [], 200),
    ],
)
async def test_outcomes_map_to_status(method, path, params, operation, outcome, status):
    service = orchestration(**{operation: outcome})
    response = await call(service, method, path, params)

    assert response.status_code == status
    getattr(service, operation).assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "params", "operation"),
    [
        ("GET", "/radar/services/", None, "list_radar_services"),
        ("GET", "/radar/services/details/", BY_ID, "get_radar_service"),
        ("DELETE", "/radar/services/stop/", BY_ID, "stop_radar_service"),
        ("DELETE", "/radar/services/s1", None, "delete_radar_service"),
    ],
)
async def test_unexpected_failures_become_500_with_the_cause(
    method, path, params, operation
):
    service = orchestration(**{operation: RuntimeError("docker gone")})
    response = await call(service, method, path, params)

    assert response.status_code == 500
    assert "docker gone" in response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "params", "operation"),
    [
        ("GET", "/radar/services/details/", BY_ID, "get_radar_service"),
        ("DELETE", "/radar/services/stop/", BY_ID, "stop_radar_service"),
        ("DELETE", "/radar/services/s1", None, "delete_radar_service"),
    ],
)
async def test_deployment_in_progress_is_not_masked_as_a_500(
    method, path, params, operation
):
    service = orchestration(**{operation: DeploymentInProgressError("deploying")})
    with pytest.raises(DeploymentInProgressError):
        await call(service, method, path, params)


@pytest.mark.asyncio
@pytest.mark.parametrize(("renamed", "status"), [(True, 200), (False, 404)])
async def test_rename_reports_missing_services(renamed, status):
    service = orchestration(rename_radar_service=renamed)
    response = await call(
        service, "PATCH", "/radar/services/s1/label", body={"display_name": "Pump"}
    )

    assert response.status_code == status
    if renamed:
        assert response.json() == {"id": "s1", "display_name": "Pump"}
