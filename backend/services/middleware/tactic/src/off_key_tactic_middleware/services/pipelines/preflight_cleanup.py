"""Reap delayed constructor jobs after their durable owner has finished."""

from off_key_core.config.logs import logger
from off_key_core.db.models import DeploymentMaintenance, PipelineActivation

from ...facades.docker import workload_labels
from ..orchestration.workload_identity import controller_id


class PreflightOrphans:
    def __init__(self, session, workloads):
        self.session = session
        self.workloads = workloads
        self.docker = workloads.async_docker

    async def sweep(self):
        controller = controller_id()
        filters = {
            "label": [
                "managed_by=tactic",
                "service_type=radar_preflight",
                f"radar_controller_id={controller}",
            ]
        }
        candidates = await self.docker.run(
            self.docker.client.services.list, filters=filters
        )
        for workload in candidates:
            try:
                labels = workload_labels(workload)
                identifier = labels.get("pipeline_activation_id")
                if not identifier or labels.get("radar_controller_id") != controller:
                    continue
                keep = await self._needed(identifier)
                await self.session.commit()
                if not keep:
                    await self.workloads.remove(workload.id)
            except Exception:
                await self.session.rollback()
                logger.exception(
                    "Pipeline preflight orphan cleanup deferred workload_id=%s",
                    workload.id,
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
