from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import docker
import pytest

from off_key_tactic_middleware.services.orchestration import radar as radar_module
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

    delete_result = MagicMock(rowcount=1)

    session = AsyncMock()
    session.execute = AsyncMock(return_value=delete_result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    service = RadarOrchestrationService(session=session, model_registry=MagicMock())
    summary = await service.teardown_managed_radar_workloads()

    assert summary["workloads_targeted"] == 2
    assert summary["docker_workloads_removed"] == 2
    assert summary["db_rows_deleted"] == 1
    delete_stmt = session.execute.await_args.args[0]
    assert "WHERE services.container_id IN" in str(delete_stmt)
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

    delete_result = MagicMock(rowcount=1)
    session = AsyncMock()
    session.execute = AsyncMock(return_value=delete_result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    service = RadarOrchestrationService(session=session, model_registry=MagicMock())

    with pytest.raises(
        RuntimeError,
        match="Failed to remove one or more managed RADAR",
    ):
        await service.teardown_managed_radar_workloads()

    delete_stmt = session.execute.await_args.args[0]
    stmt_text = str(delete_stmt)
    stmt_params = delete_stmt.compile().params
    assert "WHERE services.container_id IN" in stmt_text
    assert stmt_params == {"container_id_1": ["svc-ok"]}
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


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

    delete_result = MagicMock(rowcount=1)

    session = AsyncMock()
    session.execute = AsyncMock(return_value=delete_result)
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
