from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import docker
import pytest
from off_key_tactic_middleware.services.reconciliation import (
    RadarStatusReconciliationService,
)


def _query_result(services):
    result = MagicMock()
    result.scalars.return_value.all.return_value = services
    return result


def _service(
    *,
    service_id: str,
    status: bool,
    stage: str = "stopped",
    updated_at=None,
    created_at=None,
):
    return SimpleNamespace(
        id=service_id,
        container_id=f"ctr-{service_id}",
        container_name=f"radar-{service_id}",
        status=status,
        operational_stage=stage,
        operational_status={"stage": stage, "is_stale": False},
        operational_updated_at=updated_at,
        created_at=created_at or datetime.now(UTC),
    )


def _reconciler(*, retention_hours: int, docker_statuses: list[str]):
    service = RadarStatusReconciliationService.__new__(RadarStatusReconciliationService)
    service.terminal_service_retention_hours = retention_hours
    service._get_docker_status = AsyncMock(side_effect=docker_statuses)
    service._remove_workload_if_present = AsyncMock(return_value=False)
    return service


class _FakeAsyncDocker:
    def __init__(self):
        self.client = SimpleNamespace(
            services=SimpleNamespace(),
            containers=SimpleNamespace(),
        )

    async def run(self, func, *args, **kwargs):
        return func(*args, **kwargs)


@pytest.mark.asyncio
async def test_reconciliation_purges_old_terminal_rows_and_keeps_recent_rows():
    now = datetime.now(UTC)
    old_service = _service(
        service_id="old",
        status=False,
        updated_at=now - timedelta(hours=25),
    )
    recent_service = _service(
        service_id="recent",
        status=False,
        updated_at=now - timedelta(hours=1),
    )
    reconciliation = _reconciler(
        retention_hours=24,
        docker_statuses=["not_found", "not_found"],
    )

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _query_result([old_service, recent_service]),
            MagicMock(rowcount=0),
            MagicMock(rowcount=1),
        ]
    )

    await reconciliation._reconcile_with_session(session)

    reconciliation._remove_workload_if_present.assert_awaited_once_with("ctr-old")
    assert session.execute.await_count == 3


@pytest.mark.asyncio
async def test_reconciliation_revives_inactive_rows_when_docker_is_running():
    service = _service(service_id="live", status=False)
    reconciliation = _reconciler(
        retention_hours=24,
        docker_statuses=["running"],
    )

    session = AsyncMock()
    session.execute = AsyncMock(return_value=_query_result([service]))

    await reconciliation._reconcile_with_session(session)

    assert service.status is True
    assert service.operational_stage == "starting"
    assert service.operational_status["is_stale"] is True
    reconciliation._remove_workload_if_present.assert_not_awaited()
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconciliation_marks_active_terminal_rows_without_purging_recently():
    service = _service(service_id="dead", status=True, stage="operational")
    reconciliation = _reconciler(
        retention_hours=24,
        docker_statuses=["not_found"],
    )

    session = AsyncMock()
    session.execute = AsyncMock(return_value=_query_result([service]))

    await reconciliation._reconcile_with_session(session)

    assert service.status is False
    assert service.operational_stage == "stopped"
    reconciliation._remove_workload_if_present.assert_not_awaited()
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconciliation_skips_retry_later_statuses_without_mutation():
    service = _service(service_id="retry", status=True)
    reconciliation = _reconciler(
        retention_hours=24,
        docker_statuses=["error"],
    )
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_query_result([service]))

    await reconciliation._reconcile_with_session(session)

    assert service.status is True
    reconciliation._remove_workload_if_present.assert_not_awaited()
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_workload_removal_falls_back_to_container_on_swarm_error():
    fake_docker = _FakeAsyncDocker()
    service_container = MagicMock()
    service_container.remove = MagicMock()
    fake_docker.client.services.get = MagicMock(
        side_effect=docker.errors.APIError("This node is not a swarm manager")
    )
    fake_docker.client.containers.get = MagicMock(return_value=service_container)

    reconciler = RadarStatusReconciliationService.__new__(
        RadarStatusReconciliationService
    )
    reconciler.async_docker = fake_docker

    assert await reconciler._remove_workload_if_present("ctr-1") is True
    fake_docker.client.services.get.assert_called_once_with("ctr-1")
    fake_docker.client.containers.get.assert_called_once_with("ctr-1")
    service_container.remove.assert_called_once_with(force=True)


@pytest.mark.asyncio
async def test_reconcile_workload_removal_returns_false_when_missing_everywhere():
    fake_docker = _FakeAsyncDocker()
    fake_docker.client.services.get = MagicMock(
        side_effect=docker.errors.NotFound("missing")
    )
    fake_docker.client.containers.get = MagicMock(
        side_effect=docker.errors.NotFound("missing")
    )

    reconciler = RadarStatusReconciliationService.__new__(
        RadarStatusReconciliationService
    )
    reconciler.async_docker = fake_docker

    assert await reconciler._remove_workload_if_present("ctr-1") is False
    fake_docker.client.services.get.assert_called_once_with("ctr-1")
    fake_docker.client.containers.get.assert_called_once_with("ctr-1")


@pytest.mark.asyncio
async def test_reconciliation_keeps_running_rows_even_with_stale_heartbeat():
    service = _service(
        service_id="running",
        status=True,
        stage="operational",
        updated_at=datetime.now(UTC) - timedelta(days=7),
    )
    reconciliation = _reconciler(
        retention_hours=0,
        docker_statuses=["running"],
    )

    session = AsyncMock()
    session.execute = AsyncMock(return_value=_query_result([service]))

    await reconciliation._reconcile_with_session(session)

    assert service.status is True
    assert service.operational_stage == "operational"
    reconciliation._remove_workload_if_present.assert_not_awaited()
    session.execute.assert_awaited_once()


def test_coerce_utc_parses_iso_utc_string():
    assert RadarStatusReconciliationService._coerce_utc(
        "2024-01-01T00:00:00Z"
    ) == datetime(2024, 1, 1, 0, 0, tzinfo=UTC)


def test_coerce_utc_returns_none_on_invalid_value():
    assert RadarStatusReconciliationService._coerce_utc("not-a-timestamp") is None


def test_coerce_utc_adds_utc_timezone_for_naive_datetime():
    naive = datetime(2024, 1, 1, 12, 0, 0)
    coerce = RadarStatusReconciliationService._coerce_utc(naive)
    assert coerce == naive.replace(tzinfo=UTC)


def test_coerce_utc_converts_aware_timestamp_to_utc():
    local_tz = timezone(timedelta(hours=-8), name="PST")
    aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=local_tz)
    coerce = RadarStatusReconciliationService._coerce_utc(aware)

    assert coerce == datetime(2024, 1, 1, 20, 0, 0, tzinfo=UTC)


def test_is_purge_due_returns_true_when_reference_time_missing_and_retention_is_zero():
    service = SimpleNamespace(
        id="missing-time",
        status=False,
        operational_updated_at=None,
        created_at=None,
    )
    reconciler = RadarStatusReconciliationService.__new__(
        RadarStatusReconciliationService
    )
    reconciler.terminal_service_retention_hours = 0
    assert reconciler._is_purge_due(service) is True


def test_is_purge_due_returns_false_when_reference_time_missing_and_retention_nonzero():
    service = SimpleNamespace(
        id="missing-time",
        status=False,
        operational_updated_at=None,
        created_at=None,
    )
    reconciler = RadarStatusReconciliationService.__new__(
        RadarStatusReconciliationService
    )
    reconciler.terminal_service_retention_hours = 24
    assert reconciler._is_purge_due(service) is False


def test_mark_revived_from_terminal_stage_updates_operational_state():
    service = _service(
        service_id="revive",
        status=False,
        stage="failed",
        updated_at=None,
    )
    service.operational_status = {
        "stage": "failed",
        "detail": "old",
        "message_count": 5,
        "processed_message_count": 4,
        "is_stale": False,
    }

    RadarStatusReconciliationService._mark_revived(service)

    assert service.operational_stage == "starting"
    assert service.operational_status["stage"] == "starting"
    assert service.operational_status["detail"] == "Runtime heartbeat has not arrived"
    assert service.operational_status["is_stale"] is True
    assert service.operational_updated_at is None


def test_apply_terminal_operational_status_marks_error_only_for_failed_state():
    failed_service = _service(service_id="failed", status=False, stage="operational")
    stopped_service = _service(service_id="stopped", status=False, stage="operational")

    RadarStatusReconciliationService._apply_terminal_operational_status(
        failed_service, "failed"
    )
    RadarStatusReconciliationService._apply_terminal_operational_status(
        stopped_service, "stopped"
    )

    assert failed_service.operational_stage == "failed"
    assert failed_service.operational_status["error"] == "Docker workload is failed"
    assert stopped_service.operational_stage == "stopped"
    assert "error" not in stopped_service.operational_status
