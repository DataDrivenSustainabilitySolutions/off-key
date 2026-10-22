from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import docker
import pytest
from off_key_tactic_middleware.services import reconciliation as reconciliation_module
from off_key_tactic_middleware.services.radar_status import (
    apply_terminal_operational_status,
)
from off_key_tactic_middleware.services.reconciliation import (
    RadarStatusReconciliationService,
)
from off_key_tactic_middleware.services.time_utils import coerce_utc

from tests.support.docker import FakeAsyncDocker


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
    desired_state=None,
):
    return SimpleNamespace(
        id=service_id,
        stop_requested_at=None,
        container_id=f"ctr-{service_id}",
        container_name=f"radar-{service_id}",
        status=status,
        desired_state=desired_state or ("running" if status else "stopped"),
        operational_stage=stage,
        operational_status={"stage": stage, "is_stale": False},
        operational_updated_at=updated_at,
        created_at=created_at or datetime.now(UTC),
    )


def _reconciler(*, retention_hours: int, docker_statuses: list[str]):
    service = RadarStatusReconciliationService(
        terminal_service_retention_hours=retention_hours,
        async_docker=FakeAsyncDocker(),
    )
    service._get_docker_status = AsyncMock(side_effect=docker_statuses)
    service._remove_workload_if_present = AsyncMock(return_value=False)
    return service


@pytest.fixture(autouse=True)
def execution_locks(monkeypatch):
    # These tests isolate Docker reconciliation with explicit mock DB boundaries.
    monkeypatch.setattr(reconciliation_module, "lock_execution_records", AsyncMock())


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
        docker_statuses=[],
    )

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _query_result([old_service, recent_service]),
            MagicMock(rowcount=0),
            MagicMock(rowcount=0),
            MagicMock(rowcount=1),
        ]
    )
    session.get.side_effect = [old_service, recent_service]

    await reconciliation._reconcile_with_session(session)
    assert [
        call.args[0]
        for call in reconciliation._remove_workload_if_present.await_args_list
    ] == ["ctr-old", "ctr-recent"]
    assert session.execute.await_count == 4


@pytest.mark.asyncio
async def test_reconciliation_revives_inactive_rows_when_docker_is_running():
    service = _service(service_id="live", status=False, desired_state="running")
    reconciliation = _reconciler(
        retention_hours=24,
        docker_statuses=["running"],
    )

    session = AsyncMock()
    session.execute = AsyncMock(return_value=_query_result([service]))
    session.get.return_value = service

    await reconciliation._reconcile_with_session(session)

    assert service.status is True
    assert service.operational_stage == "starting"
    assert service.operational_status["is_stale"] is True
    reconciliation._remove_workload_if_present.assert_not_awaited()
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("previous_status", [True, False])
async def test_reconciliation_retains_desired_running_legacy_claims(previous_status):
    service = _service(
        service_id="dead",
        status=previous_status,
        desired_state="running",
        stage="operational",
        updated_at=datetime.now(UTC) - timedelta(days=7),
    )
    reconciliation = _reconciler(
        retention_hours=0,
        docker_statuses=["not_found"],
    )

    session = AsyncMock()
    session.execute = AsyncMock(return_value=_query_result([service]))
    session.get.return_value = service

    await reconciliation._reconcile_with_session(session)

    assert service.status is True
    assert service.desired_state == "running"
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
    session.get.return_value = service

    await reconciliation._reconcile_with_session(session)

    assert service.status is True
    reconciliation._remove_workload_if_present.assert_not_awaited()
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_workload_removal_returns_false_when_missing():
    fake_docker = FakeAsyncDocker()
    fake_docker.client.services.get = MagicMock(
        side_effect=docker.errors.NotFound("missing")
    )

    reconciler = RadarStatusReconciliationService(async_docker=fake_docker)

    assert await reconciler._remove_workload_if_present("ctr-1") is False
    fake_docker.client.services.get.assert_called_once_with("ctr-1")


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
    session.get.return_value = service

    await reconciliation._reconcile_with_session(session)

    assert service.status is True
    assert service.operational_stage == "operational"
    reconciliation._remove_workload_if_present.assert_not_awaited()
    session.execute.assert_awaited_once()


def test_coerce_utc_parses_iso_utc_string():
    assert coerce_utc("2024-01-01T00:00:00Z") == datetime(2024, 1, 1, 0, 0, tzinfo=UTC)


def test_coerce_utc_returns_none_on_invalid_value():
    assert coerce_utc("not-a-timestamp") is None


def test_coerce_utc_adds_utc_timezone_for_naive_datetime():
    naive = datetime(2024, 1, 1, 12, 0, 0)
    coerce = coerce_utc(naive)
    assert coerce == naive.replace(tzinfo=UTC)


def test_coerce_utc_converts_aware_timestamp_to_utc():
    local_tz = timezone(timedelta(hours=-8), name="PST")
    aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=local_tz)
    coerce = coerce_utc(aware)

    assert coerce == datetime(2024, 1, 1, 20, 0, 0, tzinfo=UTC)


def test_is_purge_due_returns_true_when_reference_time_missing_and_retention_is_zero():
    service = SimpleNamespace(
        id="missing-time",
        status=False,
        operational_updated_at=None,
        created_at=None,
    )
    reconciler = RadarStatusReconciliationService(
        terminal_service_retention_hours=0, async_docker=FakeAsyncDocker()
    )
    assert reconciler._is_purge_due(service) is True


def test_is_purge_due_returns_false_when_reference_time_missing_and_retention_nonzero():
    service = SimpleNamespace(
        id="missing-time",
        status=False,
        operational_updated_at=None,
        created_at=None,
    )
    reconciler = RadarStatusReconciliationService(
        terminal_service_retention_hours=24, async_docker=FakeAsyncDocker()
    )
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

    apply_terminal_operational_status(failed_service, "failed")
    apply_terminal_operational_status(stopped_service, "stopped")

    assert failed_service.operational_stage == "failed"
    assert failed_service.operational_status["error"] == "Docker workload is failed"
    assert stopped_service.operational_stage == "stopped"
    assert "error" not in stopped_service.operational_status


@pytest.mark.asyncio
async def test_one_failing_row_does_not_block_the_rest_of_the_pass():
    broken = _service(service_id="broken", status=False, desired_state="running")
    healthy = _service(service_id="healthy", status=False, desired_state="running")
    reconciliation = _reconciler(
        retention_hours=24, docker_statuses=["running", "running"]
    )
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_query_result([broken, healthy]))
    session.get.side_effect = [RuntimeError("constraint failed"), healthy]

    await reconciliation._reconcile_with_session(session)

    assert healthy.status is True
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_lost_database_connection_still_aborts_the_pass():
    from sqlalchemy.exc import OperationalError

    first = _service(service_id="first", status=False, desired_state="running")
    second = _service(service_id="second", status=False, desired_state="running")
    reconciliation = _reconciler(
        retention_hours=24, docker_statuses=["running", "running"]
    )
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_query_result([first, second]))
    session.get.side_effect = [OperationalError("SELECT", {}, Exception()), second]

    with pytest.raises(OperationalError):
        await reconciliation._reconcile_with_session(session)
    assert second.status is False
