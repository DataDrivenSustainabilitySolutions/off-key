"""Consistent execution lock order shared by terminal lifecycle transitions."""

from sqlalchemy import select

from .models import PipelineRun, RadarRuntimeCheckpoint


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
