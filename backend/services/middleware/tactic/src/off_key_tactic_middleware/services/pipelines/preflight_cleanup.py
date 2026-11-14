"""Reap delayed constructor jobs after their durable owner has finished."""

from off_key_core.config.logs import logger
from off_key_core.db.models import DeploymentMaintenance, PipelineActivation
from off_key_core.db.workloads import RadarWorkload
from sqlalchemy import select


class PreflightOrphans:
    def __init__(self, session, workloads):
        self.session = session
        self.workloads = workloads

    async def sweep(self):
        rows = (
            await self.session.execute(
                select(RadarWorkload.id, RadarWorkload.labels).where(
                    RadarWorkload.kind == "preflight"
                )
            )
        ).all()
        await self.session.commit()
        for workload_id, labels in rows:
            try:
                identifier = (labels or {}).get("pipeline_activation_id")
                if not identifier:
                    continue
                keep = await self._needed(identifier)
                await self.session.commit()
                if not keep:
                    await self.workloads.remove(workload_id)
            except Exception:
                await self.session.rollback()
                logger.exception(
                    "Pipeline preflight orphan cleanup deferred workload_id=%s",
                    workload_id,
                )

    async def _needed(self, identifier):
        if not identifier.startswith("release-"):
            activation = await self.session.get(
                PipelineActivation, identifier, populate_existing=True
            )
            return activation is not None and activation.phase == "preflighting"
        operation = await self.session.get(
            DeploymentMaintenance, 1, populate_existing=True
        )
        if operation is None or operation.phase != "preparing":
            return False
        run_id = identifier.removeprefix("release-")
        return any(
            monitor.get("replacement_run_id") == run_id and not monitor.get("preflight")
            for monitor in operation.monitors
        )
