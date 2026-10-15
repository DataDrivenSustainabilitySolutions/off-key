"""Pause affected monitors with durable stop intent before changing their inputs."""

from datetime import UTC, datetime

from off_key_core.db.base import get_async_session_local
from off_key_core.db.models import MonitoringService
from sqlalchemy import update

from ..domain import InfrastructureError
from .orchestration.radar_workloads import RadarWorkloadManager, get_async_docker
from .radar_status import mark_collection_monitor_stopped


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
                    MonitoringService.id.in_(ids), MonitoringService.status.is_(True)
                )
                .values(stop_requested_at=datetime.now(UTC))
            )

        workloads = RadarWorkloadManager(get_async_docker())
        for monitor_id in ids:
            try:
                async with sessions.begin() as session:
                    monitor = await session.get(
                        MonitoringService, monitor_id, with_for_update=True
                    )
                    if monitor is None or monitor.stop_requested_at is None:
                        continue
                    if monitor.config_fingerprint:
                        await workloads.remove_intent(monitor.id, monitor.container_id)
                    else:
                        await workloads.remove(monitor.container_id)
                    mark_collection_monitor_stopped(monitor)
            except Exception as exc:
                raise InfrastructureError(
                    "The catalog was not applied. Monitor stops are saved and will "
                    "be retried automatically; retry the catalog change "
                    "after they finish."
                ) from exc
        self.session.expire_all()
