from typing import TYPE_CHECKING
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logs import logger
from ..utils.enum import HealthStatus

if TYPE_CHECKING:
    from ..services.background_sync import BackgroundSyncService


async def check_database(db: AsyncSession) -> HealthStatus:
    """
    Performs the database health check.

    Args:
        db: AsyncSession database connection

    Returns:
        HealthStatus: HEALTHY if database is accessible, UNHEALTHY otherwise
    """
    try:
        await db.execute(text("SELECT 1"))
        return HealthStatus.HEALTHY
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        return HealthStatus.UNHEALTHY


def check_background_sync(sync_service: "BackgroundSyncService") -> HealthStatus:
    """
    Performs the background sync service health check.

    Args:
        sync_service: BackgroundSyncService instance

    Returns:
        HealthStatus: HEALTHY, DISABLED, or UNHEALTHY based on service state
    """
    try:
        sync_status = sync_service.get_status()
        if not sync_status.get("enabled"):
            return HealthStatus.DISABLED
        if not sync_status.get("running"):
            return HealthStatus.UNHEALTHY
        return HealthStatus.HEALTHY
    except Exception as e:
        logger.error(f"Background sync health check failed: {str(e)}")
        return HealthStatus.UNHEALTHY
