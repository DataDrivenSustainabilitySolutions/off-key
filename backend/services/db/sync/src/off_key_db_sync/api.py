"""
FastAPI application for database sync service manual triggers.

Provides REST endpoints to manually trigger sync operations.
This runs as an optional component alongside the main SyncService.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException

from off_key_core.config.logs import logger
from .config.config import get_sync_settings

# Global reference to sync service (set by main)
_sync_service = None


def set_sync_service(service):
    """Set the global sync service reference for API access"""
    global _sync_service
    _sync_service = service


def _sync_skipped_response(action: str) -> dict[str, object]:
    return {
        "status": "skipped",
        "message": (
            f"{action} skipped because SYNC_SOURCE_MODE="
            f"{get_sync_settings().config.source_mode}"
        ),
        "source_mode": get_sync_settings().config.source_mode,
    }


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
        "sync_enabled": get_sync_settings().config.enabled,
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
async def trigger_charger_sync():
    """Manually trigger charger synchronization."""
    return _sync_skipped_response("charger sync")


@app.post("/sync/chargers/clean", tags=["Sync"])
async def trigger_charger_cleanup(
    days_inactive: int,
):
    """Manually trigger charger cleanup."""
    return _sync_skipped_response(f"charger cleanup (days_inactive={days_inactive})")


@app.post("/sync/telemetry", tags=["Sync"])
async def trigger_telemetry_sync(
    limit: int = 10_000,
):
    """Manually trigger telemetry synchronization."""
    response = _sync_skipped_response(f"telemetry sync (limit={limit})")
    response["limit"] = limit
    return response


@app.get("/sync/status", tags=["Sync"])
async def get_sync_status():
    """Get background sync service status."""
    if _sync_service and _sync_service.background_sync:
        return _sync_service.background_sync.get_status()
    config = get_sync_settings().config
    return {
        "enabled": config.enabled,
        "running": False,
        "jobs": [],
        "source_mode": config.source_mode,
    }
