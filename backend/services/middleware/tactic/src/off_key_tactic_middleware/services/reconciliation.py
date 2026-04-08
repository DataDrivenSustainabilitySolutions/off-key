"""
Background reconciliation service for RADAR service status synchronization.

Periodically checks Docker container status and updates the database to keep
MonitoringService.status in sync with actual Docker state.
"""

import asyncio
from typing import Optional

import docker
import docker.errors
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from off_key_core.config.logs import logger
from off_key_core.db.models import MonitoringService
from off_key_core.db.base import get_async_session_local
from ..facades.docker import AsyncDocker, get_workload_docker_status


class RadarStatusReconciliationService:
    """Periodically syncs MonitoringService.status with actual Docker state.

    This service runs as a background task and:
    1. Fetches all MonitoringService records marked as active (status=True)
    2. Checks each service's actual Docker container status
    3. Updates the database if Docker reports the service is no longer running

    The reconciliation ensures that stale services (e.g., crashed containers)
    are properly marked as inactive in the database.
    """

    def __init__(self, interval_seconds: int = 60):
        """Initialize the reconciliation service.

        Args:
            interval_seconds: How often to run reconciliation (default: 60s)
        """
        self.interval_seconds = interval_seconds
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
            try:
                await self._task
            except asyncio.CancelledError:
                pass

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
        # Get all services marked as active
        query = select(MonitoringService).where(MonitoringService.status.is_(True))
        result = await session.execute(query)
        services = result.scalars().all()

        if not services:
            return

        updates = 0
        for service in services:
            docker_status = await self._get_docker_status(service.container_id)

            # If Docker says it's not running, mark as inactive
            if docker_status != "running":
                service.status = False
                updates += 1
                logger.info(
                    f"Service '{service.container_name}' marked inactive "
                    f"(docker_status={docker_status})"
                )

        if updates > 0:
            logger.info(f"Reconciliation complete: {updates} service(s) updated")

    async def _get_docker_status(self, container_id: str) -> str:
        """Check Docker workload status (Swarm service or container)."""
        return await get_workload_docker_status(self.async_docker, container_id)
