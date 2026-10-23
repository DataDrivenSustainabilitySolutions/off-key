"""
Database Sync Service Main Entry Point

Orchestrates both the core sync service and optional FastAPI server.
"""

import asyncio
from pathlib import Path

import uvicorn
from off_key_core.config.bootstrap import start_service
from off_key_core.config.database import get_database_settings
from off_key_core.config.logging import get_logging_settings
from off_key_core.config.logs import logger
from off_key_core.utils.tasks import run_until_first_exit

from .api import app, set_sync_service
from .config.config import get_sync_settings
from .service import SyncService


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

    start_service(
        "db-sync",
        Path(__file__).parent / "config" / "logging.yaml",
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
        # Stop when either the sync service or the API server exits.
        await run_until_first_exit(tasks)
    finally:
        logger.info("Database sync service shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
