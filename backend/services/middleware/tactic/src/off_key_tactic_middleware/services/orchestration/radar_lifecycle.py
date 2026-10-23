"""Recover persisted RADAR creation intent after request/process interruption."""

from datetime import UTC, datetime
from typing import Any, cast

from off_key_core.config.logs import logger
from off_key_core.db.models import MonitoringService
from off_key_core.schemas.radar import RadarOperationalStatus, RadarStartConfig
from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .radar_environment import build_radar_config_fingerprint, build_radar_environment
from .radar_workloads import RadarWorkloadManager
from .workload_identity import controller_id


class RadarLifecycleController:
    def __init__(self, session: AsyncSession, workloads: RadarWorkloadManager):
        self.session = session
        self.workloads = workloads

    async def complete_creation(self, service_id: str) -> MonitoringService:
        try:
            return await self._complete_creation(service_id)
        except Exception as error:
            await self.session.rollback()
            # A failed remote operation retains its input claim and recoverable
            # generation, but must be visible to operators as a failed launch.
            status = RadarOperationalStatus(
                stage="failed",
                detail="Creation needs recovery; retry start or stop this monitor.",
                error=type(error).__name__,
                updated_at=datetime.now(UTC),
                is_stale=True,
            )
            await self.session.execute(
                update(MonitoringService)
                .where(
                    MonitoringService.id == service_id,
                    MonitoringService.desired_state == "running",
                    MonitoringService.container_id.is_(None),
                    MonitoringService.stop_requested_at.is_(None),
                )
                .values(
                    operational_stage="failed",
                    operational_status=status.model_dump(
                        mode="json", exclude_none=True
                    ),
                    operational_updated_at=status.updated_at,
                )
            )
            await self.session.commit()
            raise

    async def _complete_creation(self, service_id: str) -> MonitoringService:
        """Adopt one generation; never discard an unknown Docker create outcome."""
        service = await self.session.get(
            MonitoringService, service_id, populate_existing=True
        )
        if (
            service is None
            or service.desired_state != "running"
            or service.stop_requested_at
        ):
            await self.session.rollback()
            raise RuntimeError("RADAR monitor no longer requests a running workload")
        if service.container_id:
            await self.session.commit()
            return service
        version = service.lifecycle_version
        environment = build_radar_environment(
            service_id=service.id,
            config=RadarStartConfig.model_validate(service.launch_config),
            validate_params=False,
        )
        environment["RADAR_COLLECTION_FINGERPRINT"] = (
            service.collection_fingerprint or ""
        )
        environment["RADAR_LIFECYCLE_VERSION"] = str(version)
        if build_radar_config_fingerprint(environment) != service.config_fingerprint:
            await self.session.rollback()
            raise RuntimeError(
                "Pending RADAR configuration differs from this runtime; "
                "stop and restart it"
            )
        await self.session.commit()

        workload = await self.workloads.ensure(service_id, environment)
        await self.workloads.validate_started(workload)
        attach = (
            update(MonitoringService)
            .where(
                MonitoringService.id == service_id,
                MonitoringService.lifecycle_version == version,
                MonitoringService.desired_state == "running",
                MonitoringService.stop_requested_at.is_(None),
                MonitoringService.container_id.is_(None),
            )
            .values(container_id=workload.id)
        )
        result = cast(CursorResult[Any], await self.session.execute(attach))
        await self.session.commit()
        service = await self.session.get(
            MonitoringService, service_id, populate_existing=True
        )
        owns_workload = service is not None and (
            service.desired_state == "running"
            and service.lifecycle_version == version
            and service.stop_requested_at is None
            and service.container_id == workload.id
        )
        await self.session.commit()
        if not owns_workload:
            await self.workloads.remove_intent(service_id, workload.id)
            raise RuntimeError(
                "RADAR monitor was stopped while its workload was starting"
            )
        if result.rowcount not in (0, 1):
            raise RuntimeError("Unexpected RADAR workload attachment result")
        return service

    async def recover_pending(self) -> None:
        """Finish durable requests without involving an expired HTTP request."""
        ids = list(
            (
                await self.session.scalars(
                    select(MonitoringService.id).where(
                        MonitoringService.desired_state == "running",
                        MonitoringService.status.is_(True),
                        MonitoringService.stop_requested_at.is_(None),
                        MonitoringService.container_id.is_(None),
                        MonitoringService.config_fingerprint.is_not(None),
                    )
                )
            ).all()
        )
        await self.session.commit()
        for service_id in ids:
            try:
                await self.complete_creation(service_id)
            except Exception:
                await self.session.rollback()
                logger.exception(
                    "RADAR pending creation requires retry service_id=%s", service_id
                )

    async def remove_orphans(self) -> None:
        """Retire delayed remote creations whose durable intent was deleted."""
        for workload_id in await self.workloads.list_managed_ids(
            controller_id=controller_id()
        ):
            try:
                await self._remove_orphan(workload_id)
            except Exception:
                await self.session.rollback()
                logger.exception(
                    "RADAR orphan cleanup deferred workload_id=%s", workload_id
                )

    async def _remove_orphan(self, workload_id):
        _, labels = await self.workloads.get_status_and_labels(workload_id)
        service_id = labels.get("radar_service_id")
        if not service_id:
            return  # Existing workers are reconciled through their DB IDs.
        service = await self.session.get(
            MonitoringService, service_id, populate_existing=True
        )
        remove = service is None or service.desired_state != "running"
        await self.session.commit()
        if remove:
            await self.workloads.remove(workload_id)
