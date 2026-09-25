"""
Database Sync Service Orchestrator

Orchestrates database schema initialization and health reporting.
"""

import asyncio
import signal

from off_key_core.config.logs import logger
from off_key_core.db.base import get_async_engine
from off_key_core.db.schema import bootstrap_schema
from sqlalchemy import text


class SyncService:
    """
    Main Database Sync Service that orchestrates all components

    This service:
    1. Initializes database schema
    2. Handles graceful shutdown
    3. Provides health status
    """

    def __init__(self):
        self.is_running = False
        self.initial_sync_complete = False
        self.schema_ready = False
        self.shutdown_event = asyncio.Event()

        # Logging context
        self._log_context = {"component": "sync_service", "service": "db_sync"}

    async def _initialize_database(self) -> bool:
        """
        Initialize database by creating all tables.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info("Starting database initialization", extra=self._log_context)

            async with get_async_engine().begin() as conn:
                await conn.run_sync(bootstrap_schema)

            self.schema_ready = True
            logger.info("Database tables created successfully", extra=self._log_context)
            return True

        except Exception as e:
            self.schema_ready = False
            logger.error(
                f"Database initialization failed: {e}",
                extra=self._log_context,
                exc_info=True,
            )
            return False

    async def _check_database_connection(self) -> bool:
        """
        Check if database connection is available.

        Returns:
            bool: True if connection is successful, False otherwise
        """
        try:
            async with get_async_engine().begin() as conn:
                await conn.execute(text("SELECT 1"))
            return True

        except Exception as e:
            logger.error(
                f"Database connection failed: {e}",
                extra=self._log_context,
                exc_info=True,
            )
            return False

    def _on_initial_sync_complete(self):
        """Callback when initial sync completes"""
        self.initial_sync_complete = True
        logger.info("Initial sync marked as complete", extra=self._log_context)

    async def _wait_for_database(self, max_retries: int = 30, delay: int = 2) -> bool:
        """
        Wait for database to become available.

        Args:
            max_retries: Maximum number of connection attempts
            delay: Delay between attempts in seconds

        Returns:
            bool: True if database becomes available, False if max retries exceeded
        """
        for attempt in range(1, max_retries + 1):
            logger.info(
                f"Database connection attempt {attempt}/{max_retries}",
                extra=self._log_context,
            )

            if await self._check_database_connection():
                logger.info("Database connection successful", extra=self._log_context)
                return True

            if attempt < max_retries:
                logger.info(
                    f"Waiting {delay} seconds before next attempt",
                    extra=self._log_context,
                )
                await asyncio.sleep(delay)

        logger.error(
            f"Database not available after {max_retries} attempts",
            extra=self._log_context,
        )
        return False

    async def start(self):
        """Start the database sync service"""
        if self.is_running:
            logger.warning(
                "Database sync service already running", extra=self._log_context
            )
            return

        logger.info("Starting database sync service", extra=self._log_context)

        try:
            # Wait for database to be available
            if not await self._wait_for_database():
                raise RuntimeError("Database not available")

            # Initialize database
            if not await self._initialize_database():
                raise RuntimeError("Database initialization failed")

            self.initial_sync_complete = True
            self.is_running = True

            logger.info(
                "Database sync service started successfully", extra=self._log_context
            )

        except Exception as e:
            logger.error(
                f"Failed to start database sync service: {e}",
                extra=self._log_context,
                exc_info=True,
            )

            # Cleanup on failure
            await self.stop()
            raise

    async def stop(self):
        """Stop the database sync service"""
        if not self.is_running:
            logger.info(
                "Database sync service already stopped", extra=self._log_context
            )
            return

        logger.info("Stopping database sync service", extra=self._log_context)
        shutdown_start_time = asyncio.get_event_loop().time()

        # Signal shutdown
        self.shutdown_event.set()
        self.is_running = False
        self.schema_ready = False

        try:
            shutdown_duration = asyncio.get_event_loop().time() - shutdown_start_time

            logger.info(
                f"Database sync service stopped successfully in "
                f"{shutdown_duration:.2f}s",
                extra={**self._log_context, "shutdown_duration": shutdown_duration},
            )

        except Exception as e:
            logger.error(
                f"Error during database sync service shutdown: {e}",
                extra=self._log_context,
                exc_info=True,
            )
            raise

    async def run(self):
        """Run the database sync service"""

        # Set up signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            logger.info(
                f"Received signal {signum}, initiating graceful shutdown",
                extra=self._log_context,
            )
            self.shutdown_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            # Start the service
            await self.start()

            # Keep running until shutdown signal
            logger.info(
                "Database sync service running, waiting for shutdown signal",
                extra=self._log_context,
            )
            await self.shutdown_event.wait()

        except Exception as e:
            logger.error(
                f"Unexpected error in database sync service: {e}",
                extra=self._log_context,
                exc_info=True,
            )

        finally:
            # Ensure cleanup
            await self.stop()

    def get_health_status(self):
        """Get current health status"""
        is_healthy = (
            self.is_running and self.schema_ready and self.initial_sync_complete
        )

        return {
            "status": (
                "healthy"
                if is_healthy
                else ("starting" if self.is_running else "stopped")
            ),
            "schema_ready": self.schema_ready,
            "initial_sync_complete": self.initial_sync_complete,
        }
