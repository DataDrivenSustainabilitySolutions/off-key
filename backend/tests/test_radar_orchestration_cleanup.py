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
    db_workload = MagicMock(id="db-1")
    svc_workload.remove = MagicMock()
    ctr_workload.remove = MagicMock()
    db_workload.remove = MagicMock()

    def _services_get(workload_id: str):
        if workload_id == "svc-1":
            return svc_workload
        raise docker.errors.NotFound("missing")

    def _containers_get(workload_id: str):
        if workload_id == "ctr-1":
            return ctr_workload
        if workload_id == "db-1":
            return db_workload
        raise docker.errors.NotFound("missing")

    fake_docker.client.services.list = MagicMock(return_value=[svc_workload])
    fake_docker.client.containers.list = MagicMock(return_value=[ctr_workload])
    fake_docker.client.services.get = MagicMock(side_effect=_services_get)
    fake_docker.client.containers.get = MagicMock(side_effect=_containers_get)

    monkeypatch.setattr(radar_module, "get_async_docker", lambda: fake_docker)

    select_result = MagicMock()
    select_result.all.return_value = [("db-1",)]
    delete_result = MagicMock(rowcount=1)

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[select_result, delete_result])
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    service = RadarOrchestrationService(session=session, model_registry=MagicMock())
    summary = await service.teardown_managed_radar_workloads()

    assert summary["workloads_targeted"] == 3
    assert summary["docker_workloads_removed"] == 3
    assert summary["db_rows_deleted"] == 1
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_teardown_managed_radar_workloads_rolls_back_on_remove_failure(
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

    select_result = MagicMock()
    select_result.all.return_value = []

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[select_result])
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    service = RadarOrchestrationService(session=session, model_registry=MagicMock())

    with pytest.raises(
        RuntimeError,
        match="Failed to remove one or more managed RADAR",
    ):
        await service.teardown_managed_radar_workloads()

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
