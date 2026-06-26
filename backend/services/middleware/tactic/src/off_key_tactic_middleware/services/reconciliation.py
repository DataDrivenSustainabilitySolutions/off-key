"""
Background reconciliation service for RADAR service status synchronization.

Periodically checks Docker container status and updates the database to keep
MonitoringService.status in sync with actual Docker state.
"""

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import docker
import docker.errors
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from off_key_core.config.logs import logger
from off_key_core.db.models import MonitoringService, MqttTopic
from off_key_core.db.base import get_async_session_local
from off_key_core.schemas.radar import RadarOperationalStatus
from ..facades.docker import AsyncDocker, get_workload_docker_status

_FAILED_WORKLOAD_STATES = {"dead", "exited", "failed", "rejected"}
_STOPPED_WORKLOAD_STATES = {
    "complete",
    "completed",
    "no_container_id",
    "no_tasks",
    "not_found",
    "removed",
    "stopped",
}
_TERMINAL_OPERATIONAL_STAGES = {"failed", "stopped"}
_RETRY_LATER_WORKLOAD_STATES = {"error", "unknown"}


class RadarStatusReconciliationService:
    """Periodically syncs MonitoringService.status with actual Docker state.

    This service runs as a background task and:
    1. Fetches all MonitoringService records marked as active (status=True)
    2. Checks each service's actual Docker container status
    3. Updates the database if Docker reports the service is no longer running

    The reconciliation ensures that stale services (e.g., crashed containers)
    are properly marked as inactive in the database.
    """

    def __init__(
        self,
        interval_seconds: int = 60,
        terminal_service_retention_hours: int = 24,
    ):
        """Initialize the reconciliation service.

        Args:
            interval_seconds: How often to run reconciliation (default: 60s)
        """
        self.interval_seconds = interval_seconds
        self.terminal_service_retention_hours = terminal_service_retention_hours
        self.async_docker = AsyncDocker()
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def start(self):
        """Start the reconciliation background task."""
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"Status reconciliation started (interval={self.interval_seconds}s)"
        )

    async def stop(self):
        """Stop the reconciliation background task."""
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

        # Close Docker client to release socket connections
        if self.async_docker:
            self.async_docker.close()

        logger.info("Status reconciliation stopped")

    async def _run_loop(self):
        """Main reconciliation loop."""
        while not self._stop_event.is_set():
            try:
                await self._reconcile()
            except (docker.errors.DockerException, docker.errors.APIError) as e:
                # Docker-related errors are expected and recoverable
                logger.warning(f"Docker error during reconciliation: {e}")
            except SQLAlchemyError as e:
                # Database errors are expected and recoverable
                logger.error(f"Database error during reconciliation: {e}")
            except asyncio.CancelledError:
                # Task cancellation should propagate
                raise
            except Exception as e:
                # Unexpected errors - log with full traceback for debugging
                logger.exception(f"Unexpected reconciliation error: {e}")

            # Wait for next interval or stop event
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.interval_seconds,
                )
                break  # Stop event was set
            except asyncio.TimeoutError:
                continue  # Timeout reached, run again

    async def _reconcile(self):
        """Perform a single reconciliation pass."""
        session_factory = get_async_session_local()
        async with session_factory() as session:
            try:
                await self._reconcile_with_session(session)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _reconcile_with_session(self, session: AsyncSession):
        """Reconcile DB status with Docker status.

        Args:
            session: Database session to use for queries and updates
        """
        query = select(MonitoringService)
        result = await session.execute(query)
        services = result.scalars().all()

        if not services:
            return

        updates = 0
        deleted = 0
        for service in services:
            docker_status = await self._get_docker_status(service.container_id)
            docker_state = (docker_status or "").strip().lower()
            terminal_state = (
                docker_state in _FAILED_WORKLOAD_STATES
                or docker_state in _STOPPED_WORKLOAD_STATES
            )

            if docker_state in _RETRY_LATER_WORKLOAD_STATES:
                logger.warning(
                    "Skipping service '%s' reconciliation until Docker status "
                    "is verifiable (docker_status=%s)",
                    service.container_name,
                    docker_state,
                )
                continue

            if docker_state == "running":
                if not service.status:
                    service.status = True
                    self._mark_revived(service)
                    updates += 1
                    logger.info(
                        "Service '%s' marked active again (docker_status=running)",
                        service.container_name,
                    )
                continue

            if not terminal_state:
                continue

            if service.status:
                service.status = False
                self._apply_terminal_operational_status(service, docker_status)
                updates += 1
                logger.info(
                    f"Service '{service.container_name}' marked inactive "
                    f"(docker_status={docker_status})"
                )

            if self._is_purge_due(service):
                removed_workload = await self._remove_workload_if_present(
                    service.container_id
                )
                deleted += await self._delete_service_row(session, service.id)
                logger.info(
                    "Purged terminal RADAR service '%s' "
                    "(docker_status=%s, workload_removed=%s)",
                    service.container_name,
                    docker_status,
                    removed_workload,
                )

        if updates > 0:
            logger.info(f"Reconciliation complete: {updates} service(s) updated")
        if deleted > 0:
            logger.info(f"Reconciliation purged {deleted} terminal service row(s)")

    def _is_purge_due(self, service: MonitoringService) -> bool:
        if service.status:
            return False

        reference_time = self._coerce_utc(
            service.operational_updated_at or service.created_at
        )
        if reference_time is None:
            return self.terminal_service_retention_hours == 0

        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=self.terminal_service_retention_hours
        )
        return reference_time <= cutoff

    @staticmethod
    def _coerce_utc(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    async def _delete_service_row(session: AsyncSession, service_id: str) -> int:
        await session.execute(
            delete(MqttTopic).where(MqttTopic.service_id == service_id)
        )
        delete_result = await session.execute(
            delete(MonitoringService).where(MonitoringService.id == service_id)
        )
        return int(delete_result.rowcount or 0)

    async def _remove_workload_if_present(self, container_id: Optional[str]) -> bool:
        if not container_id:
            return False
        try:
            try:
                docker_service = await self.async_docker.run(
                    self.async_docker.client.services.get, container_id
                )
                await self.async_docker.run(docker_service.remove)
                return True
            except docker.errors.NotFound:
                pass
            except Exception as exc:
                if not self._should_fallback_to_container(exc):
                    raise
                logger.debug(
                    "Skipping Swarm service removal for workload %s: %s",
                    container_id,
                    exc,
                )

            docker_container = await self.async_docker.run(
                self.async_docker.client.containers.get, container_id
            )
            await self.async_docker.run(docker_container.remove, force=True)
            return True
        except docker.errors.NotFound:
            return False

    @staticmethod
    def _should_fallback_to_container(exc: Exception) -> bool:
        if isinstance(exc, docker.errors.APIError) and exc.status_code in (
            400,
            406,
            503,
        ):
            return True
        text = str(exc).lower()
        return "this node is not a swarm manager" in text or "swarm mode" in text

    @staticmethod
    def _mark_revived(service: MonitoringService) -> None:
        raw_status = service.operational_status or {}
        stage = ""
        if isinstance(raw_status, dict):
            stage = (raw_status.get("stage") or "").strip().lower()
        stage = stage or (service.operational_stage or "").strip().lower()
        if stage not in _TERMINAL_OPERATIONAL_STAGES:
            return

        status = RadarOperationalStatus(
            stage="starting",
            detail="Runtime heartbeat has not arrived",
            message_count=0,
            processed_message_count=0,
            is_stale=True,
        ).model_dump(mode="json", exclude_none=True)
        service.operational_stage = "starting"
        service.operational_status = status
        service.operational_updated_at = None

    @staticmethod
    def _apply_terminal_operational_status(
        service: MonitoringService,
        docker_status: str,
    ) -> None:
        docker_state = (docker_status or "").strip().lower()
        stage = "failed" if docker_state in _FAILED_WORKLOAD_STATES else "stopped"
        detail = f"Docker workload is {docker_state or 'not running'}"
        now = datetime.now(timezone.utc)
        existing = service.operational_status or {}
        if not isinstance(existing, dict):
            existing = {}
        status = RadarOperationalStatus(
            stage=stage,
            detail=detail,
            progress=existing.get("progress"),
            message_count=existing.get("message_count", 0),
            processed_message_count=existing.get("processed_message_count", 0),
            last_alignment_status=existing.get("last_alignment_status"),
            error=detail if stage == "failed" else None,
            updated_at=now,
            is_stale=False,
        ).model_dump(mode="json", exclude_none=True)
        service.operational_stage = stage
        service.operational_status = status
        service.operational_updated_at = now

    async def _get_docker_status(self, container_id: str) -> str:
        """Check Docker workload status (Swarm service or container)."""
        return await get_workload_docker_status(self.async_docker, container_id)
