"""
Dependency injection providers for TACTIC middleware service.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from off_key_core.db.base import get_db_async
from .services.orchestration.radar import RadarOrchestrationService


def get_radar_orchestration_service(
    session: AsyncSession = Depends(get_db_async),
) -> RadarOrchestrationService:
    """
    Dependency injection provider for RadarOrchestrationService.

    Args:
        session: Database session from dependency injection

    Returns:
        RadarOrchestrationService: Configured service instance
    """
    return RadarOrchestrationService(session)
