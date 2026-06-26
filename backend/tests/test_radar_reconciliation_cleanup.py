from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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
        created_at=created_at or datetime.now(timezone.utc),
    )


def _reconciler(*, retention_hours: int, docker_statuses: list[str]):
    service = RadarStatusReconciliationService.__new__(RadarStatusReconciliationService)
    service.terminal_service_retention_hours = retention_hours
    service._get_docker_status = AsyncMock(side_effect=docker_statuses)
    service._remove_workload_if_present = AsyncMock(return_value=False)
    return service


@pytest.mark.asyncio
async def test_reconciliation_purges_old_terminal_rows_and_keeps_recent_rows():
    now = datetime.now(timezone.utc)
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
async def test_reconciliation_keeps_running_rows_even_with_stale_heartbeat():
    service = _service(
        service_id="running",
        status=True,
        stage="operational",
        updated_at=datetime.now(timezone.utc) - timedelta(days=7),
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
