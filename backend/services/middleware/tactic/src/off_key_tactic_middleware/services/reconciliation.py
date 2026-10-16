"""Reconcile RADAR observations outside database transactions and row locks."""

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import docker
from off_key_core.config.logs import logger
from off_key_core.db.base import get_async_session_local
from off_key_core.db.collection import lock_collection_configuration
from off_key_core.db.models import MonitoringService, MqttTopic, PipelineRun
from off_key_core.db.pipeline_locks import complete_stopped_runs, lock_execution_records
from off_key_core.schemas.radar import RadarOperationalStatus
from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.config import get_tactic_settings
from ..facades.docker import AsyncDocker, get_workload_docker_status
from .orchestration.radar_lifecycle import RadarLifecycleController
from .orchestration.radar_workloads import RadarWorkloadManager
from .radar_status import (
    TERMINAL_WORKLOAD_STATES,
    UNVERIFIED_WORKLOAD_STATES,
    apply_terminal_operational_status,
    mark_collection_monitor_stopped,
)
from .time_utils import coerce_utc


@dataclass(frozen=True, slots=True)
class _ServiceSnapshot:
    id: str
    container_id: str | None
    container_name: str
    desired_state: str
    lifecycle_version: int
    stop_requested_at: datetime | None
    config_fingerprint: str | None
    operational_updated_at: datetime | None

    @classmethod
    def capture(cls, service: MonitoringService) -> "_ServiceSnapshot":
        return cls(
            service.id,
            service.container_id,
            service.container_name,
            getattr(service, "desired_state", "running"),
            getattr(service, "lifecycle_version", 1),
            service.stop_requested_at,
            getattr(service, "config_fingerprint", None),
            service.operational_updated_at,
        )

    def matches(self, service: MonitoringService) -> bool:
        return (
            service.container_id == self.container_id
            and getattr(service, "lifecycle_version", 1) == self.lifecycle_version
            and getattr(service, "desired_state", "running") == self.desired_state
            and service.stop_requested_at == self.stop_requested_at
        )


class RadarStatusReconciliationService:
    """Snapshot, inspect with bounded concurrency, then apply short transitions."""

    def __init__(
        self,
        interval_seconds: int = 60,
        terminal_service_retention_hours: int = 24,
        *,
        async_docker: AsyncDocker | None = None,
    ) -> None:
        """Own the supplied or default Docker facade and close it when stopped."""
        self.interval_seconds = interval_seconds
        self.terminal_service_retention_hours = terminal_service_retention_hours
        self.async_docker = async_docker if async_docker is not None else AsyncDocker()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self.async_docker.close()

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._reconcile()
            except asyncio.CancelledError:
                raise
            except (docker.errors.DockerException, SQLAlchemyError):
                logger.exception(
                    "RADAR reconciliation will retry after infrastructure failure"
                )
            except Exception:
                logger.exception("RADAR reconciliation failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), self.interval_seconds)
            except TimeoutError:
                continue

    async def _reconcile(self) -> None:
        async with get_async_session_local()() as session:
            await lock_collection_configuration(session)
            failed_ids = select(PipelineRun.service_id).where(
                PipelineRun.status == "failed"
            )
            await session.execute(
                update(MonitoringService)
                .where(
                    MonitoringService.id.in_(failed_ids),
                    MonitoringService.desired_state == "running",
                    MonitoringService.stop_requested_at.is_(None),
                )
                .values(
                    desired_state="stopped",
                    stop_requested_at=datetime.now(UTC),
                    lifecycle_version=MonitoringService.lifecycle_version + 1,
                )
            )
            await session.commit()
            lifecycle = RadarLifecycleController(
                session, RadarWorkloadManager(self.async_docker)
            )
            await lifecycle.remove_orphans()
            await lifecycle.recover_pending()
            await self._reconcile_with_session(session)

    async def _reconcile_with_session(self, session: AsyncSession) -> None:
        result = await session.execute(select(MonitoringService))
        snapshots = [
            _ServiceSnapshot.capture(service) for service in result.scalars().all()
        ]
        await session.commit()
        semaphore = asyncio.Semaphore(
            get_tactic_settings().config.docker.max_concurrent_calls
        )

        async def inspect(snapshot):
            async with semaphore:
                return await self._inspect(snapshot)

        observations = await asyncio.gather(
            *(inspect(item) for item in snapshots), return_exceptions=True
        )
        for snapshot, observation in zip(snapshots, observations, strict=True):
            if isinstance(observation, BaseException):
                logger.warning(
                    "RADAR inspection deferred service_id=%s error=%s",
                    snapshot.id,
                    type(observation).__name__,
                )
                continue
            try:
                await self._apply_observation(session, snapshot, observation)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _inspect(self, snapshot: _ServiceSnapshot) -> str:
        if (
            snapshot.stop_requested_at is not None
            or snapshot.desired_state != "running"
        ):
            if snapshot.config_fingerprint:
                await RadarWorkloadManager(self.async_docker).remove_intent(
                    snapshot.id, snapshot.container_id
                )
            else:
                await self._remove_workload_if_present(snapshot.container_id)
            return "stop_confirmed"
        if snapshot.config_fingerprint and snapshot.container_id is None:
            return "pending_creation"
        return await self._get_docker_status(snapshot.container_id)

    async def _apply_observation(
        self, session: AsyncSession, snapshot: _ServiceSnapshot, observation: str
    ) -> None:
        if observation == "stop_confirmed":
            await lock_execution_records(session, [snapshot.id])
        service = await session.get(
            MonitoringService, snapshot.id, with_for_update=True, populate_existing=True
        )
        if service is None or not snapshot.matches(service):
            return
        if observation == "stop_confirmed":
            await self._apply_stopped(session, service)
        elif observation == "running":
            if not service.status:
                service.status = True
                self._mark_revived(service)
        elif observation in TERMINAL_WORKLOAD_STATES:
            # A heartbeat arriving after the Docker snapshot is newer evidence.
            if service.operational_updated_at == snapshot.operational_updated_at:
                self._apply_terminal(service, observation)
        elif observation in UNVERIFIED_WORKLOAD_STATES:
            logger.warning(
                "RADAR workload status unverifiable service_id=%s", service.id
            )

    async def _apply_stopped(
        self, session: AsyncSession, service: MonitoringService
    ) -> None:
        if getattr(service, "desired_state", None) == "deleted":
            await self._delete_service_row(session, service.id)
        elif service.stop_requested_at is not None or service.status:
            mark_collection_monitor_stopped(service)
            await complete_stopped_runs(session, [service.id])
        elif self._is_purge_due(service):
            await self._delete_service_row(session, service.id)

    def _apply_terminal(self, service: MonitoringService, docker_status: str) -> None:
        if getattr(service, "desired_state", "running") == "running":
            # Legacy rows have no config fingerprint but their Swarm tasks can
            # also restart. Desired intent owns the claim, including rows whose
            # derived status was cleared by an older controller.
            service.status = True
            apply_terminal_operational_status(service, docker_status)
        elif self._is_purge_due(service):
            # Hold the claim until a later unlocked inspection confirms shutdown.
            service.desired_state = "deleted"
            service.lifecycle_version = (
                getattr(service, "lifecycle_version", 1) or 1
            ) + 1
            service.stop_requested_at = datetime.now(UTC)
            service.status = True
            return
        elif service.status:
            service.status = False
            apply_terminal_operational_status(service, docker_status)

    def _is_purge_due(self, service: MonitoringService) -> bool:
        if service.status:
            return False
        reference_time = coerce_utc(
            service.operational_updated_at or service.created_at
        )
        if reference_time is None:
            return self.terminal_service_retention_hours == 0
        return reference_time <= datetime.now(UTC) - timedelta(
            hours=self.terminal_service_retention_hours
        )

    _coerce_utc = staticmethod(coerce_utc)

    @staticmethod
    async def _delete_service_row(session: AsyncSession, service_id: str) -> int:
        await complete_stopped_runs(session, [service_id])
        await session.execute(
            delete(MqttTopic).where(MqttTopic.service_id == service_id)
        )
        result = await session.execute(
            delete(MonitoringService).where(MonitoringService.id == service_id)
        )
        return int(result.rowcount or 0)

    async def _remove_workload_if_present(self, container_id: str | None) -> bool:
        return await RadarWorkloadManager(self.async_docker).remove(container_id)

    @staticmethod
    def _mark_revived(service: MonitoringService) -> None:
        raw = service.operational_status or {}
        stage = (raw.get("stage") or service.operational_stage or "").strip().lower()
        if stage in {"failed", "stopped"}:
            service.operational_stage = "starting"
            service.operational_status = RadarOperationalStatus(
                stage="starting",
                detail="Runtime heartbeat has not arrived",
                is_stale=True,
            ).model_dump(mode="json", exclude_none=True)
            service.operational_updated_at = None

    async def _get_docker_status(self, container_id: str | None) -> str:
        return await get_workload_docker_status(self.async_docker, container_id or "")
