from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import docker
import pytest

from off_key_tactic_middleware.services.orchestration import radar as radar_module
from off_key_tactic_middleware.facades.docker import get_workload_docker_status
from off_key_tactic_middleware.services.orchestration.radar import (
    RadarOrchestrationService,
)


class _FakeAsyncDocker:
    def __init__(self):
        self.client = SimpleNamespace(
            services=SimpleNamespace(),
            containers=SimpleNamespace(),
        )

    async def run(self, func, *args, **kwargs):
        return func(*args, **kwargs)


@pytest.mark.asyncio
async def test_teardown_managed_radar_workloads_removes_workloads_and_clears_db(
    monkeypatch,
):
    fake_docker = _FakeAsyncDocker()

    svc_workload = MagicMock(id="svc-1")
    ctr_workload = MagicMock(id="ctr-1")
    svc_workload.remove = MagicMock()
    ctr_workload.remove = MagicMock()

    def _services_get(workload_id: str):
        if workload_id == "svc-1":
            return svc_workload
        raise docker.errors.NotFound("missing")

    def _containers_get(workload_id: str):
        if workload_id == "ctr-1":
            return ctr_workload
        raise docker.errors.NotFound("missing")

    fake_docker.client.services.list = MagicMock(return_value=[svc_workload])
    fake_docker.client.containers.list = MagicMock(return_value=[ctr_workload])
    fake_docker.client.services.get = MagicMock(side_effect=_services_get)
    fake_docker.client.containers.get = MagicMock(side_effect=_containers_get)

    monkeypatch.setattr(radar_module, "get_async_docker", lambda: fake_docker)

    service_id_result = MagicMock()
    service_id_result.scalars.return_value.all.return_value = ["svc-1"]

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[service_id_result, MagicMock(rowcount=0), MagicMock(rowcount=1)]
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    service = RadarOrchestrationService(session=session, model_registry=MagicMock())
    summary = await service.teardown_managed_radar_workloads()

    assert summary["workloads_targeted"] == 2
    assert summary["docker_workloads_removed"] == 2
    assert summary["db_rows_deleted"] == 1
    statements = [call.args[0] for call in session.execute.await_args_list]
    assert "WHERE services.container_id IN" in str(statements[0])
    assert "DELETE FROM mqtt_topics" in str(statements[1])
    assert "DELETE FROM services" in str(statements[2])
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_teardown_managed_radar_workloads_raises_on_remove_failure(
    monkeypatch,
):
    fake_docker = _FakeAsyncDocker()
    broken_workload = MagicMock(id="svc-1")
    broken_workload.remove = MagicMock(side_effect=RuntimeError("boom"))

    fake_docker.client.services.list = MagicMock(return_value=[broken_workload])
    fake_docker.client.containers.list = MagicMock(return_value=[])
    fake_docker.client.services.get = MagicMock(return_value=broken_workload)
    fake_docker.client.containers.get = MagicMock(
        side_effect=docker.errors.NotFound("missing")
    )

    monkeypatch.setattr(radar_module, "get_async_docker", lambda: fake_docker)

    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    service = RadarOrchestrationService(session=session, model_registry=MagicMock())

    with pytest.raises(
        RuntimeError,
        match="Failed to remove one or more managed RADAR",
    ):
        await service.teardown_managed_radar_workloads()

    session.execute.assert_not_awaited()
    session.rollback.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_teardown_managed_radar_workloads_cleans_up_successes_on_partial_failure(
    monkeypatch,
):
    fake_docker = _FakeAsyncDocker()

    ok_workload = MagicMock(id="svc-ok")
    ok_workload.remove = MagicMock()
    broken_workload = MagicMock(id="svc-broken")
    broken_workload.remove = MagicMock(side_effect=RuntimeError("boom"))

    def _services_get(workload_id: str):
        if workload_id == "svc-ok":
            return ok_workload
        if workload_id == "svc-broken":
            return broken_workload
        raise docker.errors.NotFound("missing")

    fake_docker.client.services.list = MagicMock(
        return_value=[ok_workload, broken_workload]
    )
    fake_docker.client.containers.list = MagicMock(return_value=[])
    fake_docker.client.services.get = MagicMock(side_effect=_services_get)
    fake_docker.client.containers.get = MagicMock(
        side_effect=docker.errors.NotFound("missing")
    )

    monkeypatch.setattr(radar_module, "get_async_docker", lambda: fake_docker)

    service_id_result = MagicMock()
    service_id_result.scalars.return_value.all.return_value = ["svc-ok"]
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[service_id_result, MagicMock(rowcount=0), MagicMock(rowcount=1)]
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    service = RadarOrchestrationService(session=session, model_registry=MagicMock())

    with pytest.raises(
        RuntimeError,
        match="Failed to remove one or more managed RADAR",
    ):
        await service.teardown_managed_radar_workloads()

    delete_stmt = session.execute.await_args_list[0].args[0]
    stmt_text = str(delete_stmt)
    stmt_params = delete_stmt.compile().params
    assert "WHERE services.container_id IN" in stmt_text
    assert stmt_params == {"container_id_1": ["svc-ok"]}
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_workload_status_falls_back_to_container_when_swarm_unavailable():
    fake_docker = _FakeAsyncDocker()
    container = MagicMock(status="running")
    container.reload = MagicMock()

    fake_docker.client.services.get = MagicMock(
        side_effect=docker.errors.APIError("This node is not a swarm manager")
    )
    fake_docker.client.containers.get = MagicMock(return_value=container)

    status = await get_workload_docker_status(fake_docker, "ctr-1")

    assert status == "running"
    fake_docker.client.containers.get.assert_called_once_with("ctr-1")
    container.reload.assert_called_once()


@pytest.mark.asyncio
async def test_teardown_managed_radar_workloads_handles_non_swarm_docker(
    monkeypatch,
):
    fake_docker = _FakeAsyncDocker()

    ctr_workload = MagicMock(id="ctr-1")
    ctr_workload.remove = MagicMock()

    fake_docker.client.services.list = MagicMock(
        side_effect=docker.errors.APIError("This node is not a swarm manager")
    )
    fake_docker.client.containers.list = MagicMock(return_value=[ctr_workload])
    fake_docker.client.services.get = MagicMock(
        side_effect=docker.errors.APIError("This node is not a swarm manager")
    )
    fake_docker.client.containers.get = MagicMock(return_value=ctr_workload)

    monkeypatch.setattr(radar_module, "get_async_docker", lambda: fake_docker)

    service_id_result = MagicMock()
    service_id_result.scalars.return_value.all.return_value = ["svc-1"]

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[service_id_result, MagicMock(rowcount=0), MagicMock(rowcount=1)]
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    service = RadarOrchestrationService(session=session, model_registry=MagicMock())
    summary = await service.teardown_managed_radar_workloads()

    assert summary["workloads_targeted"] == 1
    assert summary["docker_workloads_removed"] == 1
    assert summary["db_rows_deleted"] == 1
    fake_docker.client.containers.list.assert_called_once()
    fake_docker.client.containers.get.assert_called_once_with("ctr-1")
    ctr_workload.remove.assert_called_once()
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_radar_service_deletes_db_row_after_removing_workload(
    monkeypatch,
):
    fake_docker = _FakeAsyncDocker()
    db_row = SimpleNamespace(
        id="svc-1",
        container_id="ctr-1",
        container_name="radar-static",
        status=True,
    )
    query_result = MagicMock()
    query_result.scalars.return_value.first.return_value = db_row

    workload = MagicMock(id="ctr-1")
    workload.remove = MagicMock()

    fake_docker.client.services.get = MagicMock(
        side_effect=docker.errors.NotFound("missing")
    )
    fake_docker.client.containers.get = MagicMock(return_value=workload)
    monkeypatch.setattr(radar_module, "get_async_docker", lambda: fake_docker)

    session = AsyncMock()
    service_delete_result = MagicMock(rowcount=1)
    session.execute = AsyncMock(
        side_effect=[query_result, MagicMock(rowcount=0), service_delete_result]
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    service = RadarOrchestrationService(session=session, model_registry=MagicMock())

    assert await service.stop_radar_service(container_name="radar-static") is True
    workload.remove.assert_called_once_with(force=True)
    assert session.execute.await_count == 3
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_radar_service_deletes_db_row_when_workload_is_missing(
    monkeypatch,
):
    fake_docker = _FakeAsyncDocker()
    db_row = SimpleNamespace(
        id="svc-1",
        container_id="missing-ctr",
        container_name="radar-static",
        status=True,
    )
    query_result = MagicMock()
    query_result.scalars.return_value.first.return_value = db_row

    fake_docker.client.services.get = MagicMock(
        side_effect=docker.errors.NotFound("missing")
    )
    fake_docker.client.containers.get = MagicMock(
        side_effect=docker.errors.NotFound("missing")
    )
    monkeypatch.setattr(radar_module, "get_async_docker", lambda: fake_docker)

    session = AsyncMock()
    service_delete_result = MagicMock(rowcount=1)
    session.execute = AsyncMock(
        side_effect=[query_result, MagicMock(rowcount=0), service_delete_result]
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    service = RadarOrchestrationService(session=session, model_registry=MagicMock())

    assert await service.stop_radar_service(container_name="radar-static") is True
    assert session.execute.await_count == 3
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_radar_service_removes_running_workload_and_db_rows(monkeypatch):
    fake_docker = _FakeAsyncDocker()
    db_row = SimpleNamespace(
        id="svc-1",
        container_id="ctr-1",
        container_name="radar-static",
        status=True,
    )
    query_result = MagicMock()
    query_result.scalars.return_value.first.return_value = db_row

    workload = MagicMock(id="ctr-1")
    workload.remove = MagicMock()

    fake_docker.client.services.get = MagicMock(
        side_effect=docker.errors.NotFound("missing")
    )
    fake_docker.client.containers.get = MagicMock(return_value=workload)
    monkeypatch.setattr(radar_module, "get_async_docker", lambda: fake_docker)

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[query_result, MagicMock(rowcount=0), MagicMock(rowcount=1)]
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    service = RadarOrchestrationService(session=session, model_registry=MagicMock())

    assert await service.delete_radar_service("svc-1") is True
    workload.remove.assert_called_once_with(force=True)
    assert session.execute.await_count == 3
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_radar_service_leaves_db_row_when_workload_remove_fails(
    monkeypatch,
):
    fake_docker = _FakeAsyncDocker()
    db_row = SimpleNamespace(
        id="svc-1",
        container_id="ctr-1",
        container_name="radar-static",
        status=True,
    )
    query_result = MagicMock()
    query_result.scalars.return_value.first.return_value = db_row

    workload = MagicMock(id="ctr-1")
    workload.remove = MagicMock(side_effect=RuntimeError("boom"))

    fake_docker.client.services.get = MagicMock(
        side_effect=docker.errors.NotFound("missing")
    )
    fake_docker.client.containers.get = MagicMock(return_value=workload)
    monkeypatch.setattr(radar_module, "get_async_docker", lambda: fake_docker)

    session = AsyncMock()
    session.execute = AsyncMock(return_value=query_result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    service = RadarOrchestrationService(session=session, model_registry=MagicMock())

    assert await service.delete_radar_service("svc-1") is False
    workload.remove.assert_called_once_with(force=True)
    session.execute.assert_awaited_once()
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_startup_validation_raises_with_logs_when_container_exits(
    monkeypatch,
):
    fake_docker = _FakeAsyncDocker()
    exited_workload = SimpleNamespace(id="ctr-1")
    exited_container = MagicMock(status="exited")
    exited_container.reload = MagicMock()
    exited_container.logs = MagicMock(
        return_value=b"Failed to start RADAR service: missing dependency"
    )

    fake_docker.client.services.get = MagicMock(
        side_effect=docker.errors.NotFound("missing")
    )
    fake_docker.client.containers.get = MagicMock(return_value=exited_container)
    monkeypatch.setattr(radar_module, "get_async_docker", lambda: fake_docker)
    monkeypatch.setattr(
        radar_module,
        "get_tactic_settings",
        lambda: SimpleNamespace(
            config=SimpleNamespace(radar_startup_grace_seconds=0.0)
        ),
    )

    session = AsyncMock()
    service = RadarOrchestrationService(session=session, model_registry=MagicMock())

    with pytest.raises(RuntimeError, match="missing dependency"):
        await service._validate_radar_workload_started(exited_workload)

    exited_container.reload.assert_called_once()
    exited_container.logs.assert_called_once_with(tail=120)


@pytest.mark.asyncio
async def test_create_radar_service_removes_workload_when_db_commit_fails(
    monkeypatch,
):
    fake_docker = _FakeAsyncDocker()
    monkeypatch.setattr(radar_module, "get_async_docker", lambda: fake_docker)

    query_result = MagicMock()
    query_result.scalars.return_value.first.return_value = None

    session = AsyncMock()
    session.execute = AsyncMock(return_value=query_result)
    session.add = MagicMock()
    session.commit = AsyncMock(side_effect=RuntimeError("commit failed"))
    session.rollback = AsyncMock()

    workload = SimpleNamespace(id="workload-1")
    service = RadarOrchestrationService(session=session, model_registry=MagicMock())
    service._build_radar_environment = MagicMock(
        return_value={
            "SERVICE_ID": "service-1",
            "RADAR_SUBSCRIPTION_TOPICS": "charger/+/live-telemetry/#",
            "RADAR_MONITORING_STRATEGY": "adaptive_stream",
            "RADAR_MODEL_TYPE": "knn",
        }
    )
    service._create_radar_workload = AsyncMock(return_value=workload)
    service._validate_radar_workload_started = AsyncMock()
    service._remove_created_workload_after_failure = AsyncMock()

    with pytest.raises(RuntimeError, match="commit failed"):
        await service.create_radar_service(
            container_name="radar-duplicate",
            mqtt_topics=["charger/+/live-telemetry/#"],
            model_type="knn",
        )

    session.rollback.assert_awaited_once()
    service._remove_created_workload_after_failure.assert_awaited_once_with(workload)


@pytest.mark.asyncio
async def test_existing_active_service_with_missing_workload_is_recreated(
    monkeypatch,
):
    fake_docker = _FakeAsyncDocker()
    monkeypatch.setattr(radar_module, "get_async_docker", lambda: fake_docker)

    db_row = SimpleNamespace(
        id="old-svc",
        container_id="missing-workload",
        container_name="radar-stale",
        mqtt_topic=["charger/+/live-telemetry/#"],
        status=True,
        operational_status={},
        operational_stage="starting",
        operational_updated_at=None,
    )
    query_result = MagicMock()
    query_result.scalars.return_value.first.return_value = db_row

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[query_result, MagicMock(rowcount=0), MagicMock(rowcount=1)]
    )
    session.add = MagicMock()
    session.commit = AsyncMock()

    service = RadarOrchestrationService(session=session, model_registry=MagicMock())
    service._build_radar_environment = MagicMock(
        return_value={
            "SERVICE_ID": "service-1",
            "RADAR_SUBSCRIPTION_TOPICS": "charger/+/live-telemetry/#",
            "RADAR_MONITORING_STRATEGY": "adaptive_stream",
            "RADAR_MODEL_TYPE": "knn",
        }
    )
    service._get_docker_status = AsyncMock(return_value="not_found")
    service._create_radar_workload = AsyncMock(
        return_value=SimpleNamespace(id="new-workload")
    )
    service._validate_radar_workload_started = AsyncMock()

    created = await service.create_radar_service(
        container_name="radar-stale",
        mqtt_topics=["charger/+/live-telemetry/#"],
        model_type="knn",
    )

    assert created.container_name == "radar-stale"
    assert created.container_id == "new-workload"
    assert session.commit.await_count == 2
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_existing_active_service_rejects_config_fingerprint_mismatch(
    monkeypatch,
):
    fake_docker = _FakeAsyncDocker()
    monkeypatch.setattr(radar_module, "get_async_docker", lambda: fake_docker)

    db_row = SimpleNamespace(
        id="svc-existing",
        container_id="workload-1",
        container_name="radar-existing",
        mqtt_topic=["charger/+/live-telemetry/#"],
        status=True,
    )
    query_result = MagicMock()
    query_result.scalars.return_value.first.return_value = db_row

    session = AsyncMock()
    session.execute = AsyncMock(return_value=query_result)

    service = RadarOrchestrationService(session=session, model_registry=MagicMock())
    service._build_radar_environment = MagicMock(
        return_value={
            "SERVICE_ID": "service-1",
            "RADAR_SUBSCRIPTION_TOPICS": "charger/+/live-telemetry/#",
            "RADAR_MONITORING_STRATEGY": "adaptive_stream",
            "RADAR_MODEL_TYPE": "knn",
        }
    )
    service._get_docker_status = AsyncMock(return_value="running")
    service._get_workload_labels = AsyncMock(
        return_value={"radar_config_fingerprint": "different"}
    )

    with pytest.raises(ValueError, match="different RADAR configuration"):
        await service.create_radar_service(
            container_name="radar-existing",
            mqtt_topics=["charger/+/live-telemetry/#"],
            model_type="knn",
        )

    assert db_row.status is True
    session.commit.assert_not_awaited()
