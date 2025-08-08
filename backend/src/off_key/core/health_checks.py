from typing import TYPE_CHECKING
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logs import logger

if TYPE_CHECKING:
    from ..services.background_sync import BackgroundSyncService


async def check_database(db: AsyncSession) -> str:
    """
    Performs the database health check.

    Args:
        db: AsyncSession database connection

    Returns:
        str: "healthy" if database is accessible, "unhealthy" otherwise
    """
    try:
        await db.execute(text("SELECT 1"))
        return "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        return "unhealthy"


def check_background_sync(sync_service: "BackgroundSyncService") -> str:
    """
    Performs the background sync service health check.

    Args:
        sync_service: BackgroundSyncService instance

    Returns:
        str: "healthy", "disabled", or "unhealthy" based on service state
    """
    try:
        sync_status = sync_service.get_status()
        if not sync_status.get("enabled"):
            return "disabled"
        if not sync_status.get("running"):
            return "unhealthy"
        return "healthy"
    except Exception as e:
        logger.error(f"Background sync health check failed: {str(e)}")
        return "unhealthy"
