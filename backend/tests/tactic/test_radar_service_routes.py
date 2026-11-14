"""The monitor routes validate lookups and map outcomes to HTTP."""

from unittest.mock import AsyncMock

import pytest
from off_key_api_gateway.providers import get_radar_orchestration_service
from off_key_core.db.maintenance import DeploymentInProgressError

from tests.support.gateway import gateway_app, member, returning
from tests.support.http import asgi_client


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


async def call(service, method, path, body=None):
    app = gateway_app(
        member("admin"),
        overrides={get_radar_orchestration_service: returning(service)},
    )
    async with asgi_client(app) as client:
        return await client.request(method, "/v1/monitors" + path, json=body)


DETAIL = {
    "id": "s1",
    "display_name": "Pump",
    "stream_ids": ["r1"],
    "status": True,
    "container_name": "radar-s1",
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "operation", "outcome", "status"),
    [
        ("GET", "/s1", "get_radar_service", DETAIL, 200),
        ("GET", "/s1", "get_radar_service", None, 404),
        ("POST", "/s1/stop", "stop_radar_service", True, 200),
        ("POST", "/s1/stop", "stop_radar_service", False, 404),
        ("DELETE", "/s1", "delete_radar_service", True, 204),
        ("DELETE", "/s1", "delete_radar_service", False, 404),
        ("GET", "", "list_radar_services", [], 200),
    ],
)
async def test_outcomes_map_to_status(method, path, operation, outcome, status):
    service = orchestration(**{operation: outcome})
    response = await call(service, method, path)

    assert response.status_code == status, response.text
    getattr(service, operation).assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "operation"),
    [
        ("GET", "", "list_radar_services"),
        ("GET", "/s1", "get_radar_service"),
        ("POST", "/s1/stop", "stop_radar_service"),
        ("DELETE", "/s1", "delete_radar_service"),
    ],
)
async def test_unexpected_failures_are_not_turned_into_an_answer_with_the_cause(
    method, path, operation
):
    service = orchestration(**{operation: RuntimeError("docker gone")})
    # The server answers a bare 500; no route echoes the cause to the caller.
    with pytest.raises(RuntimeError, match="docker gone"):
        await call(service, method, path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "operation"),
    [
        ("GET", "/s1", "get_radar_service"),
        ("POST", "/s1/stop", "stop_radar_service"),
        ("DELETE", "/s1", "delete_radar_service"),
    ],
)
async def test_a_deployment_in_progress_is_answered_as_unavailable(
    method, path, operation
):
    service = orchestration(**{operation: DeploymentInProgressError("deploying")})
    response = await call(service, method, path)
    assert (response.status_code, response.json()) == (503, {"detail": "deploying"})


@pytest.mark.asyncio
@pytest.mark.parametrize(("renamed", "status"), [(True, 200), (False, 404)])
async def test_rename_reports_missing_monitors(renamed, status):
    service = orchestration(rename_radar_service=renamed)
    response = await call(service, "PATCH", "/s1", body={"display_name": "Pump"})

    assert response.status_code == status
    if renamed:
        assert response.json() == {"id": "s1", "display_name": "Pump"}
