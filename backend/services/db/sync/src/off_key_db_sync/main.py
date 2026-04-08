"""
Database Sync Service Main Entry Point

Orchestrates both the core sync service and optional FastAPI server.
"""

import asyncio
import uvicorn
from pathlib import Path

from off_key_core.config.database import get_database_settings
from off_key_core.config.env import load_env
from off_key_core.config.logging import get_logging_settings
from off_key_core.config.validation import validate_settings
from off_key_core.config.logs import (
    load_yaml_config,
    logger,
    log_startup_logging_configuration,
)
from .config.config import get_sync_settings
from .service import SyncService
from .api import app, set_sync_service


async def run_api_server(sync_service: SyncService):
    """Run FastAPI server in background"""
    # Set the sync service reference for API access
    set_sync_service(sync_service)

    # Configure uvicorn
    sync_config = get_sync_settings().config
    config = uvicorn.Config(
        app,
        host=sync_config.api_host,
        port=sync_config.api_port,
        log_config=None,  # Disable uvicorn's logging, use our logger
    )
    server = uvicorn.Server(config)

    logger.info(
        "Starting FastAPI server on %s:%s",
        sync_config.api_host,
        sync_config.api_port,
    )

    # Run server
    await server.serve()


async def main():
    """Main entry point for database sync service"""

    load_env()

    # Initialize logging before validation so startup failures are structured.
    service_logging_config = Path(__file__).parent / "config" / "logging.yaml"
    load_yaml_config(str(service_logging_config))
    log_startup_logging_configuration("db-sync")

    validate_settings(
        [
            ("logging", get_logging_settings),
            ("database", get_database_settings),
            ("sync", lambda: get_sync_settings().config),
        ],
        context="DB sync configuration",
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
