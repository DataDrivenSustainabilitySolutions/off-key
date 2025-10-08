from typing import TYPE_CHECKING

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from off_key_core.db.base import get_db_async

if TYPE_CHECKING:
    from .services.services import MonitoringAsyncService


def get_monitoring_service(
    db: AsyncSession = Depends(get_db_async),
) -> "MonitoringAsyncService":
    """
    Dependency provider for the MonitoringAsyncService.

    Args:
        db: AsyncSession injected by FastAPI dependency system

    Returns:
        MonitoringAsyncService instance configured with the database session
    """
    from .services.services import MonitoringAsyncService

    return MonitoringAsyncService(db)
