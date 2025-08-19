"""
Background Sync Service for Charger and Telemetry Data

Handles periodic synchronization of charger and telemetry data from Pionix Cloud
using APScheduler. Runs in the background of the main API service.
"""

import asyncio
from datetime import datetime
from typing import Optional, Callable
from sqlalchemy.ext.asyncio import AsyncSession

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from off_key_core.config.config import settings
from off_key_core.config.logs import logger
from off_key_core.db.base import AsyncSessionLocal
from .chargers import ChargersSyncService
from .telemetry import TelemetrySyncService

# Factory type definitions
ChargerSyncFactory = Callable[[AsyncSession], ChargersSyncService]
TelemetrySyncFactory = Callable[[AsyncSession], TelemetrySyncService]


class BackgroundSyncService:
    """
    Background service for periodic data synchronization

    Features:
    - Periodic charger synchronization
    - Periodic telemetry synchronization
    - Configurable intervals
    - Proper error handling and logging
    - Health monitoring integration
    """

    def __init__(
        self,
        charger_sync_factory: ChargerSyncFactory,
        telemetry_sync_factory: TelemetrySyncFactory,
    ):
        self.charger_sync_factory = charger_sync_factory
        self.telemetry_sync_factory = telemetry_sync_factory
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.is_running = False

        # Logging context
        self._log_context = {"component": "background_sync", "service": "api"}

    async def start(self):
        """Start the background sync service"""
        if not settings.SYNC_ENABLED:
            logger.info("Background sync service disabled", extra=self._log_context)
            return

        if self.is_running:
            logger.warning(
                "Background sync service already running", extra=self._log_context
            )
            return

        logger.info("Starting background sync service", extra=self._log_context)

        # Initialize scheduler
        self.scheduler = AsyncIOScheduler()

        # Add charger sync job
        if settings.SYNC_CHARGERS_INTERVAL > 0:
            self.scheduler.add_job(
                self._sync_chargers,
                trigger=IntervalTrigger(seconds=settings.SYNC_CHARGERS_INTERVAL),
                id="charger_sync",
                name="Charger Sync",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=300,  # 5 minutes
            )
            logger.info(
                f"Charger sync scheduled every "
                f"{settings.SYNC_CHARGERS_INTERVAL} seconds",
                extra=self._log_context,
            )

        # Add telemetry sync job
        if settings.SYNC_TELEMETRY_INTERVAL > 0:
            self.scheduler.add_job(
                self._sync_telemetry,
                trigger=IntervalTrigger(seconds=settings.SYNC_TELEMETRY_INTERVAL),
                id="telemetry_sync",
                name="Telemetry Sync",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=300,  # 5 minutes
            )
            logger.info(
                f"Telemetry sync scheduled every "
                f"{settings.SYNC_TELEMETRY_INTERVAL} seconds",
                extra=self._log_context,
            )

        # Start scheduler
        self.scheduler.start()
        self.is_running = True

        logger.info(
            "Background sync service started successfully", extra=self._log_context
        )

        # Run initial sync if enabled
        if settings.SYNC_ON_STARTUP:
            asyncio.create_task(self._initial_sync())

    async def stop(self):
        """Stop the background sync service"""
        if not self.is_running:
            return

        logger.info("Stopping background sync service", extra=self._log_context)

        if self.scheduler:
            self.scheduler.shutdown(wait=True)

        self.is_running = False
        logger.info("Background sync service stopped", extra=self._log_context)

    async def _initial_sync(self):
        """Run initial sync on startup"""
        logger.info("Running initial sync on startup", extra=self._log_context)

        try:
            # Small delay to ensure database is ready
            await asyncio.sleep(2)

            # Run charger sync first
            await self._sync_chargers()

            # Small delay between syncs
            await asyncio.sleep(1)

            # Run telemetry sync
            await self._sync_telemetry()

            logger.info("Initial sync completed successfully", extra=self._log_context)

        except Exception as e:
            logger.error(
                f"Initial sync failed: {e}", extra=self._log_context, exc_info=True
            )

    async def _sync_chargers(self):
        """Sync chargers from Pionix Cloud"""
        sync_start = datetime.now()

        try:
            logger.info("Starting charger sync", extra=self._log_context)

            # Create database session
            async with AsyncSessionLocal() as session:
                sync_service = self.charger_sync_factory(session)
                await sync_service.sync_chargers()

            sync_duration = (datetime.now() - sync_start).total_seconds()
            logger.info(
                f"Charger sync completed in {sync_duration:.2f}s",
                extra={
                    **self._log_context,
                    "sync_type": "chargers",
                    "duration": sync_duration,
                },
            )

        except Exception as e:
            sync_duration = (datetime.now() - sync_start).total_seconds()
            logger.error(
                f"Charger sync failed after {sync_duration:.2f}s: {e}",
                extra={
                    **self._log_context,
                    "sync_type": "chargers",
                    "duration": sync_duration,
                    "error": str(e),
                },
                exc_info=True,
            )

    async def _sync_telemetry(self):
        """Sync telemetry data from Pionix Cloud"""
        sync_start = datetime.now()

        try:
            logger.info("Starting telemetry sync", extra=self._log_context)

            # Create database session
            async with AsyncSessionLocal() as session:
                sync_service = self.telemetry_sync_factory(session)
                await sync_service.sync_telemetry(limit=settings.SYNC_TELEMETRY_LIMIT)

            sync_duration = (datetime.now() - sync_start).total_seconds()
            logger.info(
                f"Telemetry sync completed in {sync_duration:.2f}s",
                extra={
                    **self._log_context,
                    "sync_type": "telemetry",
                    "duration": sync_duration,
                    "limit": settings.SYNC_TELEMETRY_LIMIT,
                },
            )

        except Exception as e:
            sync_duration = (datetime.now() - sync_start).total_seconds()
            logger.error(
                f"Telemetry sync failed after {sync_duration:.2f}s: {e}",
                extra={
                    **self._log_context,
                    "sync_type": "telemetry",
                    "duration": sync_duration,
                    "limit": settings.SYNC_TELEMETRY_LIMIT,
                    "error": str(e),
                },
                exc_info=True,
            )

    def get_status(self) -> dict:
        """Get sync service status"""
        if not self.scheduler:
            return {"enabled": settings.SYNC_ENABLED, "running": False, "jobs": []}

        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run": (
                        job.next_run_time.isoformat() if job.next_run_time else None
                    ),
                    "trigger": str(job.trigger),
                }
            )

        return {
            "enabled": settings.SYNC_ENABLED,
            "running": self.is_running,
            "jobs": jobs,
        }
