"""Persist monitor presentation independently of workload identity and lifecycle."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from off_key_api_gateway.api.access import current_member, operational_access
from off_key_api_gateway.api.v1 import monitors
from off_key_core.db.maintenance import DeploymentInProgressError
from off_key_core.schemas.radar import RadarServiceLabel, RadarStartConfig
from off_key_core.utils.enum import RoleEnum
from off_key_tactic_middleware import deployment
from off_key_tactic_middleware.api.v1 import radar as radar_api
from off_key_tactic_middleware.services.orchestration import radar
from pydantic import ValidationError


def configuration():
    return RadarStartConfig(
        container_name="stable-workload",
        mqtt_topics=["telemetry/room-input/temperature"],
        display_name="Climate",
        model_type="pyod_iforest",
    ).model_dump(mode="json")


def row(config=None):
    return SimpleNamespace(
        id="monitor",
        container_id="workload",
        container_name="stable-workload",
        launch_config=config,
        mqtt_topic=["telemetry/room-input/temperature"],
        status=True,
        created_at=None,
    )


def orchestration(record):
    service = object.__new__(radar.RadarOrchestrationService)
    service.session = AsyncMock()
    service.session.scalar.return_value = None
    result = MagicMock()
    result.scalars.return_value.first.return_value = record
    result.scalars.return_value.all.return_value = [record]
    service.session.execute.return_value = result
    service.workloads = SimpleNamespace(
        get_status_and_labels=AsyncMock(return_value=("running", {}))
    )
    return service


@pytest.fixture(autouse=True)
def isolate_lifecycle(monkeypatch):
    monkeypatch.setattr(radar, "lock_collection_configuration", AsyncMock())
    monkeypatch.setattr(
        radar, "derive_operational_status", lambda *_: {"stage": "operational"}
    )


@pytest.mark.parametrize(
    "value", ["", "   ", "bad\nname", "bad\x00name", "x" * 121, 123]
)
def test_service_names_are_strict_at_both_boundaries(value):
    with pytest.raises(ValidationError):
        RadarServiceLabel(display_name=value)
    with pytest.raises(ValidationError):
        RadarStartConfig(
            container_name="stable",
            mqtt_topics=["telemetry/room-input/value"],
            display_name=value,
        )


@pytest.mark.asyncio
async def test_overview_metadata_comes_from_saved_configuration_without_docker_calls():
    service = orchestration(row(configuration()))
    result = await service.list_radar_services()
    assert result[0]["display_name"] == "Climate"
    assert result[0]["monitoring_strategy"] == "static_baseline"
    assert result[0]["model_type"] == "pyod_iforest"
    assert "configuration" not in result[0]
    service.workloads.get_status_and_labels.assert_not_awaited()


@pytest.mark.asyncio
async def test_detail_exposes_detector_settings_without_connection_credentials():
    config = configuration() | {"mqtt_config": {"password": "private-test-password"}}
    service = orchestration(row(config))
    detail = await service.get_radar_service(container_name="stable-workload")
    assert detail["configuration"] == {
        "monitoring": config["monitoring"],
        "performance_config": config["performance_config"],
    }
    assert "mqtt_config" not in detail


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [None, configuration()])
async def test_rename_preserves_launch_settings_and_identity_and_locks_the_row(config):
    record = row(config)
    service = orchestration(record)
    assert await service.rename_radar_service("monitor", "  New climate name  ")
    assert record.launch_config == {
        **(config or {}),
        "display_name": "New climate name",
    }
    assert (record.id, record.container_id, record.container_name) == (
        "monitor",
        "workload",
        "stable-workload",
    )
    assert record.mqtt_topic == ["telemetry/room-input/temperature"]
    assert "FOR UPDATE" in str(service.session.execute.await_args.args[0])
    radar.lock_collection_configuration.assert_awaited_once_with(service.session)
    service.session.commit.assert_awaited_once()
    service.workloads.get_status_and_labels.assert_not_awaited()


@pytest.mark.asyncio
async def test_rename_missing_record_and_deployment_lock_do_not_commit():
    service = orchestration(None)
    assert not await service.rename_radar_service("missing", "Name")
    service.session.commit.assert_not_awaited()
    service.session.scalar.return_value = SimpleNamespace(
        phase="preparing", revision="release"
    )
    with pytest.raises(DeploymentInProgressError):
        await service.rename_radar_service("monitor", "Name")
    service.session.commit.assert_not_awaited()


@pytest.mark.parametrize("role,expected", [(RoleEnum.user, 403), (RoleEnum.admin, 200)])
def test_gateway_service_rename_obeys_operational_write_permissions(
    role, expected, monkeypatch
):
    app = FastAPI()
    app.include_router(
        monitors.router,
        prefix="/v1/monitors",
        dependencies=[Depends(operational_access)],
    )
    app.dependency_overrides[current_member] = lambda: SimpleNamespace(role=role)
    rename = AsyncMock(
        return_value={"service_id": "monitor", "display_name": "Climate"}
    )
    monkeypatch.setattr(monitors.tactic, "rename_radar_service", rename)
    with TestClient(app) as client:
        response = client.patch(
            "/v1/monitors/monitor/label", json={"display_name": "Climate"}
        )
    assert response.status_code == expected, response.text
    if role == RoleEnum.user:
        rename.assert_not_awaited()
    else:
        rename.assert_awaited_once_with("monitor", "Climate")


def test_missing_service_label_returns_404_without_claiming_success():
    app = FastAPI()
    app.include_router(radar_api.router, prefix="/api/v1/orchestration")
    app.dependency_overrides[radar_api.get_radar_orchestration_service] = lambda: (
        SimpleNamespace(rename_radar_service=AsyncMock(return_value=False))
    )
    with TestClient(app) as client:
        response = client.patch(
            "/api/v1/orchestration/radar/services/missing/label",
            json={"display_name": "Name"},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_renamed_legacy_monitor_still_captures_restart_configuration(monkeypatch):
    record = row({"display_name": "New legacy name"})
    session = AsyncMock()
    session.get.return_value = None
    session.scalars.return_value = [record]
    captured = configuration()
    monkeypatch.setattr(deployment, "lock_collection_configuration", AsyncMock())
    monkeypatch.setattr(
        deployment, "captured_configuration", lambda *_: captured.copy()
    )
    docker = SimpleNamespace(
        client=SimpleNamespace(services=SimpleNamespace(get=MagicMock())),
        run=AsyncMock(
            return_value=SimpleNamespace(
                attrs={"Spec": {"TaskTemplate": {"ContainerSpec": {"Env": []}}}}
            )
        ),
    )
    assert await deployment.capture_existing(
        session, SimpleNamespace(async_docker=docker)
    ) == {"captured": 1}
    assert record.launch_config["display_name"] == "New legacy name"
    assert (
        RadarStartConfig.model_validate(record.launch_config).container_name
        == "stable-workload"
    )


@pytest.mark.parametrize("age,stale", [(60, False), (240, True)])
def test_status_freshness_without_a_docker_probe(age, stale):
    from datetime import UTC, datetime, timedelta

    from off_key_tactic_middleware.services.radar_status import (
        derive_operational_status,
    )

    updated = datetime.now(UTC) - timedelta(seconds=age)
    record = row(configuration())
    record.operational_stage = "operational"
    record.operational_updated_at = updated
    record.operational_status = {
        "stage": "operational",
        "updated_at": updated.isoformat(),
    }
    status = derive_operational_status(record)
    assert status["is_stale"] is stale
    assert status["stage"] == "operational"
    if stale:
        assert status["detail"] == "Runtime heartbeat is stale"
