"""
FastAPI application for database sync service manual triggers.

Provides REST endpoints to manually trigger sync operations.
This runs as an optional component alongside the main SyncService.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from off_key_core.config.config import get_settings
from off_key_core.config.logs import logger
from off_key_core.db.base import get_db_async
from off_key_core.clients.provider import get_charger_api_client
from .services.chargers import ChargersSyncService
from .services.telemetry import TelemetrySyncService

settings = get_settings()

# Global reference to sync service (set by main)
_sync_service = None


def set_sync_service(service):
    """Set the global sync service reference for API access"""
    global _sync_service
    _sync_service = service


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan manager"""
    logger.info("Database sync API started")
    yield
    logger.info("Database sync API stopped")


# FastAPI app
app = FastAPI(
    title="Off-Key Database Sync Service",
    description=(
        "Database initialization and synchronization service with manual trigger API"
    ),
    lifespan=lifespan,
)


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    if _sync_service:
        return _sync_service.get_health_status()

    return {
        "status": "unhealthy",
        "message": "Sync service not initialized",
        "sync_enabled": settings.SYNC_ENABLED,
    }


@app.get("/ready/schema", tags=["Health"])
async def schema_ready_check():
    """
    Readiness endpoint for schema/migration completion.

    Returns HTTP 200 only after database schema initialization has completed.
    Use this for startup ordering of dependent services.
    """
    if _sync_service and _sync_service.schema_ready:
        return {"status": "ready", "schema_ready": True}

    raise HTTPException(
        status_code=503,
        detail="Schema initialization still in progress",
    )


@app.post("/sync/chargers", tags=["Sync"])
async def trigger_charger_sync(db: AsyncSession = Depends(get_db_async)):
    """Manually trigger charger synchronization."""
    try:
        client = get_charger_api_client()
        service = ChargersSyncService(db, client)
        await service.sync_chargers()
        return {"status": "success", "message": "Charger sync completed"}
    except Exception as e:
        logger.error(f"Manual charger sync failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@app.post("/sync/chargers/clean", tags=["Sync"])
async def trigger_charger_cleanup(
    days_inactive: int, db: AsyncSession = Depends(get_db_async)
):
    """Manually trigger charger cleanup."""
    try:
        client = get_charger_api_client()
        service = ChargersSyncService(db, client)
        await service.clean_chargers(days_inactive=days_inactive)
        return {
            "status": "success",
            "message": f"Charger cleanup completed (days_inactive={days_inactive})",
        }
    except Exception as e:
        logger.error(f"Manual charger cleanup failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@app.post("/sync/telemetry", tags=["Sync"])
async def trigger_telemetry_sync(
    limit: int = 10_000, db: AsyncSession = Depends(get_db_async)
):
    """Manually trigger telemetry synchronization."""
    try:
        client = get_charger_api_client()
        service = TelemetrySyncService(db, client)
        await service.sync_telemetry(limit=limit)
        return {
            "status": "success",
            "message": "Telemetry sync completed",
            "limit": limit,
        }
    except Exception as e:
        logger.error(f"Manual telemetry sync failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@app.get("/sync/status", tags=["Sync"])
async def get_sync_status():
    """Get background sync service status."""
    if _sync_service and _sync_service.background_sync:
        return _sync_service.background_sync.get_status()
    return {"enabled": settings.SYNC_ENABLED, "running": False, "jobs": []}
