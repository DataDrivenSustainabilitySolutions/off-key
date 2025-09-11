from typing import TYPE_CHECKING

from fastapi import Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from off_key_core.clients.base_client import ChargerAPIClient
from off_key_core.clients.provider import get_charger_api_client
from off_key_core.db.base import get_db_async

if TYPE_CHECKING:
    from .services.background_sync import BackgroundSyncService
    from .services.chargers import ChargersSyncService
    from .services.telemetry import TelemetrySyncService


def get_background_sync_service(request: Request) -> "BackgroundSyncService":
    """
    Dependency provider to get the singleton BackgroundSyncService instance
    from the application state.

    Args:
        request: FastAPI Request object providing access to app.state

    Returns:
        BackgroundSyncService instance from app state

    Raises:
        AttributeError: If service not initialized (shouldn't happen after startup)
    """
    # Import here to avoid circular imports
    from .services.background_sync import BackgroundSyncService

    service = request.app.state.background_sync
    if not isinstance(service, BackgroundSyncService):
        raise ValueError("BackgroundSyncService not properly initialized in app state")

    return service




def get_chargers_sync_service(
    db: AsyncSession = Depends(get_db_async),
    client: ChargerAPIClient = Depends(get_charger_api_client),
) -> "ChargersSyncService":
    """
    Dependency provider for ChargersSyncService.

    Args:
        db: AsyncSession injected by FastAPI dependency system
        client: ChargerAPIClient injected by FastAPI dependency system

    Returns:
        ChargersSyncService instance configured with database session and API client
    """
    from .services.chargers import ChargersSyncService

    return ChargersSyncService(db, client)


def get_telemetry_sync_service(
    db: AsyncSession = Depends(get_db_async),
    client: ChargerAPIClient = Depends(get_charger_api_client),
) -> "TelemetrySyncService":
    """
    Dependency provider for TelemetrySyncService.

    Args:
        db: AsyncSession injected by FastAPI dependency system
        client: ChargerAPIClient injected by FastAPI dependency system

    Returns:
        TelemetrySyncService instance configured with database session and API client
    """
    from .services.telemetry import TelemetrySyncService

    return TelemetrySyncService(db, client)
