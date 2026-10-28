"""
Dependency injection providers for TACTIC middleware service.

Routers under api/v1 are transport-only: they receive services from these
providers and never touch a database session, query or transaction directly
(test_tactic_data_api_architecture enforces this). New services take the
AsyncSession directly; the existing repositories stay but are not extended.
"""

from functools import partial

from fastapi import Depends, HTTPException, Request
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
from .services.accounts.members import MemberService
from .services.accounts.remembered_sessions import RememberedSessionService
from .services.accounts.users import UserService
from .services.catalogue.broker_check import BrokerCheck
from .services.catalogue.system import SystemService
from .services.catalogue.system_ingress import SystemIngress
from .services.catalogue.system_live import SystemLiveService
from .services.data import (
    AnomalyService,
    ChargerQueryService,
    FavoriteService,
    MonitoringEvidenceService,
    TelemetryQueryService,
)
from .services.orchestration.radar import RadarOrchestrationService
from .services.pipelines.activation import PipelineActivations
from .services.pipelines.forms import start_form_monitor
from .services.pipelines.library import PipelineLibrary


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


def get_system_service(session: AsyncSession = Depends(get_db_async)) -> SystemService:
    """Saved catalogue, collection status and policy changes."""
    return SystemService(session)


def get_live_service(request: Request) -> SystemLiveService:
    """The process-wide live observation manager started with the app."""
    service = getattr(request.app.state, "system_live", None)
    if service is None:
        raise HTTPException(503, "Live observation is unavailable.")
    return service


def get_broker_check(request: Request) -> BrokerCheck:
    """The process-wide, bounded broker reachability checker."""
    service = getattr(request.app.state, "broker_check", None)
    if service is None:
        raise HTTPException(503, "Connection checks are unavailable.")
    return service


def get_system_ingress(request: Request) -> SystemIngress:
    """The process-wide recording ingress; it owns every recorded broker client."""
    service = getattr(request.app.state, "system_ingress", None)
    if service is None:
        raise HTTPException(503, "Recording is unavailable.")
    return service


def get_pipeline_library(
    session: AsyncSession = Depends(get_db_async),
) -> PipelineLibrary:
    return PipelineLibrary(session)


def get_pipeline_activations(
    session: AsyncSession = Depends(get_db_async),
) -> PipelineActivations:
    return PipelineActivations(session)


def get_form_monitor_starter(session: AsyncSession = Depends(get_db_async)):
    """Start a setup-form monitor as its equivalent pipeline activation."""
    return partial(start_form_monitor, session)


def get_member_service(session: AsyncSession = Depends(get_db_async)) -> MemberService:
    return MemberService(session)


def get_remembered_session_service(
    session: AsyncSession = Depends(get_db_async),
) -> RememberedSessionService:
    return RememberedSessionService(session)
