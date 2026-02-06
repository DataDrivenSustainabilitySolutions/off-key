"""
Database Sync Service Main Entry Point

Orchestrates both the core sync service and optional FastAPI server.
"""

import asyncio
import uvicorn

from off_key_core.config.config import get_settings
from off_key_core.config.logs import setup_logging, LogFormat, logger
from .config import sync_settings
from .service import SyncService
from .api import app, set_sync_service

settings = get_settings()


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

    logger.info(
        f"Starting FastAPI server on "
        f"{sync_settings.config.api_host}:{sync_settings.config.api_port}"
    )

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

    sync_service = SyncService()
    sync_task = asyncio.create_task(sync_service.run(), name="off-key-db-sync-service")
    api_task = asyncio.create_task(
        run_api_server(sync_service), name="off-key-db-sync-api"
    )

    tasks = {sync_task, api_task}
    try:
        # Wait until either the sync service stops or the API server exits
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        # Propagate exceptions from whichever task finished first
        for task in done:
            task.result()

    finally:
        # Ensure both tasks are stopped
        for task in tasks:
            if task.done():
                continue
            task.cancel()

        for task in tasks:
            if task.done():
                continue
            try:
                await task
            except asyncio.CancelledError:
                pass

        logger.info("Database sync service shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
