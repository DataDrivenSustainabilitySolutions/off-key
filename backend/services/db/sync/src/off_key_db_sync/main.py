"""
Database Sync Service Main Entry Point

Orchestrates both the core sync service and optional FastAPI server.
"""

import asyncio
import uvicorn

from off_key_core.config.config import settings
from off_key_core.config.logs import setup_logging, LogFormat, logger
from .config import sync_settings
from .service import SyncService
from .api import app, set_sync_service


async def run_api_server(sync_service: SyncService):
    """Run FastAPI server in background"""
    # Set the sync service reference for API access
    set_sync_service(sync_service)

    # Configure uvicorn
    config = uvicorn.Config(
        app,
        host=sync_settings.config.api_host,
        port=sync_settings.config.api_port,
        log_config=None,  # Disable uvicorn's logging, use our logger
    )
    server = uvicorn.Server(config)

    logger.info(f"Starting FastAPI server on {sync_settings.config.api_host}:{sync_settings.config.api_port}")

    # Run server
    await server.serve()


async def main():
    """Main entry point for database sync service"""

    # Initialize logging
    log_format = (
        LogFormat.JSON if settings.LOG_FORMAT.lower() == "json" else LogFormat.SIMPLE
    )
    setup_logging(
        app_name="off-key-db-sync",
        log_level=settings.LOG_LEVEL,
        log_format=log_format,
        enable_correlation=True,
    )

    logger.info("Starting Off-Key database sync service")

    # Create sync service
    sync_service = SyncService()

    # Start sync service
    await sync_service.start()

    # Run FastAPI server alongside sync service
    api_task = asyncio.create_task(run_api_server(sync_service))

    try:
        # Wait for shutdown signal (handled by service)
        await sync_service.shutdown_event.wait()

    finally:
        # Cancel API server
        api_task.cancel()
        try:
            await api_task
        except asyncio.CancelledError:
            pass

        logger.info("Database sync service shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
