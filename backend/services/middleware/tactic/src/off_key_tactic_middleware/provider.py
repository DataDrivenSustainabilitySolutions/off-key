"""
Dependency injection providers for TACTIC middleware service.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, Request

from off_key_core.db.base import get_db_async, get_db_sync_transactional
from .models.registry import ModelRegistryService
from .repositories import (
    ChargerRepository,
    TelemetryRepository,
    UserRepository,
    FavoriteRepository,
    AnomalyRepository,
    ModelRegistryAdminRepository,
)
from .services.orchestration.radar import RadarOrchestrationService
from .services.admin_models import ModelRegistryAdminService
from .services.data import (
    ChargerQueryService,
    TelemetryQueryService,
    UserService,
    FavoriteService,
    AnomalyService,
)


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


def get_charger_query_service(
    session: AsyncSession = Depends(get_db_async),
) -> ChargerQueryService:
    """Dependency provider for charger data query use cases."""
    return ChargerQueryService(ChargerRepository(session))


def get_telemetry_query_service(
    session: AsyncSession = Depends(get_db_async),
) -> TelemetryQueryService:
    """Dependency provider for telemetry data query use cases."""
    return TelemetryQueryService(TelemetryRepository(session))


def get_user_service(
    session: AsyncSession = Depends(get_db_async),
) -> UserService:
    """Dependency provider for user/account use cases."""
    return UserService(session, UserRepository(session))


def get_favorite_service(
    session: AsyncSession = Depends(get_db_async),
) -> FavoriteService:
    """Dependency provider for favorites use cases."""
    return FavoriteService(session, FavoriteRepository(session))


def get_anomaly_service(
    session: AsyncSession = Depends(get_db_async),
) -> AnomalyService:
    """Dependency provider for anomaly use cases."""
    return AnomalyService(session, AnomalyRepository(session))


def get_model_registry_admin_service(
    session: Session = Depends(get_db_sync_transactional),
) -> ModelRegistryAdminService:
    """Dependency provider for model-registry admin use cases."""
    return ModelRegistryAdminService(ModelRegistryAdminRepository(session))
