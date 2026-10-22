"""Run records shared by pipeline activation and release."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from off_key_core.db.pipelines import PipelineRun
from sqlalchemy import select


async def ensure_predecessor_run(
    session,
    *,
    service_id: str,
    launch_config: dict[str, Any] | None,
    created_at: datetime,
    execution: dict[str, Any] | None = None,
    revision_id: str | None = None,
) -> PipelineRun:
    """Return the service's run, recording one for a monitor started without it."""
    run = await session.scalar(
        select(PipelineRun).where(PipelineRun.service_id == service_id)
    )
    if run is None:
        run = PipelineRun(
            id=str(uuid4()),
            service_id=service_id,
            revision_id=revision_id,
            execution=execution,
            launch_config=launch_config,
            layout={},
            status="running",
            created_at=created_at,
        )
        session.add(run)
        await session.flush()
    return run
