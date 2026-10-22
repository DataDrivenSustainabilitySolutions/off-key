"""Pause affected monitors with durable stop intent before changing their inputs."""

from off_key_core.db.base import get_async_session_local
from off_key_core.db.models import MonitoringService
from off_key_core.db.pipeline_claims import monitor_claim_condition
from off_key_core.db.pipeline_locks import complete_stopped_runs, lock_execution_records
from sqlalchemy import update

from ..domain import InfrastructureError
from .orchestration.monitor_intent import (
    complete_stop,
    request_stop_values,
    retire_workload,
)
from .orchestration.radar_workloads import RadarWorkloadManager, get_async_docker


class CollectionMonitorService:
    def __init__(self, session):
        self.session = session

    async def pause_monitors(self, affected: list[dict]) -> None:
        if not affected:
            return
        # The caller holds the catalog lock. Commit stop intent independently:
        # Docker removal cannot be rolled back with a failed catalog transaction.
        sessions = get_async_session_local()
        ids = [item["id"] for item in affected]
        async with sessions.begin() as session:
            await session.execute(
                update(MonitoringService)
                .where(
                    MonitoringService.id.in_(ids),
                    monitor_claim_condition(),
                    MonitoringService.desired_state != "deleted",
                )
                .values(**request_stop_values())
            )

        # At this point the catalogue caller has only prepared/validated a change.
        # Persisted stop intent survives cancellation; release its catalogue and
        # row locks before waiting for Docker and revalidate revisions afterward.
        await self.session.commit()

        workloads = RadarWorkloadManager(get_async_docker())
        for monitor_id in ids:
            try:
                async with sessions.begin() as session:
                    monitor = await session.get(MonitoringService, monitor_id)
                    if (
                        monitor is None
                        or monitor.stop_requested_at is None
                        or monitor.desired_state not in {"stopped", "deleted"}
                    ):
                        continue
                    workload_id = monitor.container_id
                    version = monitor.lifecycle_version
                    fingerprint = monitor.config_fingerprint
                await retire_workload(workloads, monitor_id, workload_id, fingerprint)
                async with sessions.begin() as session:
                    await lock_execution_records(session, [monitor_id])
                    monitor = await session.get(
                        MonitoringService, monitor_id, with_for_update=True
                    )
                    if (
                        monitor is not None
                        and monitor.lifecycle_version == version
                        and monitor.container_id == workload_id
                        and monitor.stop_requested_at is not None
                        and monitor.desired_state == "stopped"
                    ):
                        complete_stop(monitor)
                        await complete_stopped_runs(session, [monitor_id])
            except Exception as exc:
                raise InfrastructureError(
                    "The catalog was not applied. Monitor stops are saved and will "
                    "be retried automatically; retry the catalog change "
                    "after they finish."
                ) from exc
        self.session.expire_all()
