"""Consistent execution lock order shared by terminal lifecycle transitions."""

from datetime import UTC, datetime

from sqlalchemy import case, func, select, update

from .models import MonitoringService, PipelineRun, RadarRuntimeCheckpoint
from .run_events import run_event


async def lock_execution_records(session, service_ids: list[str]) -> None:
    """Lock checkpoint, then run, before callers lock or delete service rows.

    Worker fatal writes use this order. Service deletion also cascades into its
    checkpoint, so locking only the run before service deletion is insufficient.
    """
    identifiers = sorted(set(service_ids))
    if not identifiers:
        return
    await session.execute(
        select(RadarRuntimeCheckpoint.service_id)
        .where(RadarRuntimeCheckpoint.service_id.in_(identifiers))
        .order_by(RadarRuntimeCheckpoint.service_id)
        .with_for_update()
    )
    await session.execute(
        select(PipelineRun.id)
        .where(PipelineRun.service_id.in_(identifiers))
        .order_by(PipelineRun.id)
        .with_for_update()
    )


async def complete_stopped_runs(session, service_ids: list[str]) -> None:
    """End stopped executions without replacing a recorded terminal outcome.

    Callers first acquire ``lock_execution_records``, then validate their locked
    service lifecycle intent. This update belongs to that same transaction.
    """
    if not service_ids:
        return
    # The service row, and the last status it holds, is deleted after this.
    last_status = (
        select(MonitoringService.operational_status)
        .where(MonitoringService.id == PipelineRun.service_id)
        .scalar_subquery()
    )
    ended = await session.execute(
        update(PipelineRun)
        .where(PipelineRun.service_id.in_(service_ids), PipelineRun.ended_at.is_(None))
        .values(
            status=case(
                (PipelineRun.status.in_(["failed", "cancelled"]), PipelineRun.status),
                else_="stopped",
            ),
            ended_at=datetime.now(UTC),
            final_status=func.coalesce(PipelineRun.final_status, last_status),
        )
        .returning(PipelineRun.id, PipelineRun.status)
        .execution_options(synchronize_session="fetch")
    )
    session.add_all(
        run_event(run_id, "run_ended", stage=status, detail={"status": status})
        for run_id, status in ended.all()
    )
