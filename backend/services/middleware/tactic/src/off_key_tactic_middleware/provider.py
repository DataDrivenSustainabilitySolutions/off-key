"""
Dependency injection providers for TACTIC middleware service.
"""

from fastapi import Depends
from off_key_core.db.base import get_db_async
from sqlalchemy.ext.asyncio import AsyncSession

from .repositories import (
    AnomalyRepository,
    ChargerRepository,
    FavoriteRepository,
    MonitoringEvidenceRepository,
    TelemetryRepository,
    UserRepository,
)
from .services.data import (
    AnomalyService,
    ChargerQueryService,
    FavoriteService,
    MonitoringEvidenceService,
    TelemetryQueryService,
    UserService,
)
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


def get_monitoring_evidence_service(
    session: AsyncSession = Depends(get_db_async),
) -> MonitoringEvidenceService:
    """Dependency provider for monitoring-evidence queries."""
    return MonitoringEvidenceService(MonitoringEvidenceRepository(session))
