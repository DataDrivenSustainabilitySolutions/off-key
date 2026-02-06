"""
Dependency injection providers for TACTIC middleware service.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends, HTTPException, Request

from off_key_core.db.base import get_db_async
from .models.registry import ModelRegistryService
from .services.orchestration.radar import RadarOrchestrationService


def get_model_registry_service(request: Request) -> ModelRegistryService:
    """Get initialized model registry service from app state."""
    registry = getattr(request.app.state, "model_registry", None)
    is_ready = getattr(request.app.state, "model_registry_ready", False)

    if registry is None or not is_ready:
        raise HTTPException(
            status_code=503,
            detail=(
                "Model registry is not ready. Database/schema initialization may still "
                "be in progress."
            ),
        )

    return registry


def get_radar_orchestration_service(
    session: AsyncSession = Depends(get_db_async),
    model_registry: ModelRegistryService = Depends(get_model_registry_service),
) -> RadarOrchestrationService:
    """
    Dependency injection provider for RadarOrchestrationService.

    Args:
        session: Database session from dependency injection

    Returns:
        RadarOrchestrationService: Configured service instance
    """
    return RadarOrchestrationService(session, model_registry)
