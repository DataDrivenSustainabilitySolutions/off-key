"""
FastAPI application for database schema service health checks.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException

from off_key_core.config.logs import logger

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
    description="Database schema initialization and readiness service",
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
