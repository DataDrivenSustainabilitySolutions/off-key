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
        self.schema_ready = False
        self.shutdown_event = asyncio.Event()

    async def _initialize_database(self) -> bool:
        """
        Initialize database by creating all tables.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info("Starting database initialization")

            async with get_async_engine().begin() as conn:
                await conn.run_sync(bootstrap_schema)

            self.schema_ready = True
            logger.info("Database tables created successfully")
            return True

        except Exception as e:
            self.schema_ready = False
            logger.error(
                f"Database initialization failed: {e}",
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
                exc_info=True,
            )
            return False

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
            )

            if await self._check_database_connection():
                logger.info("Database connection successful")
                return True

            if attempt < max_retries:
                logger.info(
                    f"Waiting {delay} seconds before next attempt",
                )
                await asyncio.sleep(delay)

        logger.error(
            f"Database not available after {max_retries} attempts",
        )
        return False

    async def start(self):
        """Start the database sync service"""
        if self.is_running:
            logger.warning("Database sync service already running")
            return

        logger.info("Starting database sync service")

        try:
            # Wait for database to be available
            if not await self._wait_for_database():
                raise RuntimeError("Database not available")

            # Initialize database
            if not await self._initialize_database():
                raise RuntimeError("Database initialization failed")

            self.is_running = True

            logger.info("Database sync service started successfully")

        except Exception as e:
            logger.error(
                f"Failed to start database sync service: {e}",
                exc_info=True,
            )

            # Cleanup on failure
            await self.stop()
            raise

    async def stop(self):
        """Stop the database sync service"""
        if not self.is_running:
            logger.info("Database sync service already stopped")
            return

        logger.info("Stopping database sync service")
        self.shutdown_event.set()
        self.is_running = False
        self.schema_ready = False
        logger.info("Database sync service stopped")

    async def run(self):
        """Run the database sync service"""

        # Set up signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            logger.info(
                f"Received signal {signum}, initiating graceful shutdown",
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
            )
            await self.shutdown_event.wait()

        except Exception as e:
            logger.error(
                f"Unexpected error in database sync service: {e}",
                exc_info=True,
            )

        finally:
            # Ensure cleanup
            await self.stop()

    def get_health_status(self):
        """Get current health status"""
        return {
            "status": (
                "healthy"
                if self.is_running and self.schema_ready
                else ("starting" if self.is_running else "stopped")
            ),
            "schema_ready": self.schema_ready,
            # Kept in the /health shape the gateway waits on; equals schema_ready.
            "initial_sync_complete": self.schema_ready,
        }
