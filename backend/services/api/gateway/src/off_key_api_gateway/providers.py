"""The domain services each request works with, one database session apiece.

Routers under api/v1 are transport-only: they receive services from these
providers and never touch a database session, query or transaction directly
(test_api_architecture enforces this). New services take the AsyncSession
directly; the existing repositories stay but are not extended.
"""

from functools import partial

from fastapi import Depends, HTTPException, Request
from off_key_core.db.base import get_db_async
from off_key_tactic_middleware.repositories import (
    AnomalyRepository,
    FavoriteRepository,
    UserRepository,
)
from off_key_tactic_middleware.services.accounts.agents import AgentService
from off_key_tactic_middleware.services.accounts.members import MemberService
from off_key_tactic_middleware.services.accounts.remembered_sessions import (
    RememberedSessionService,
)
from off_key_tactic_middleware.services.accounts.users import UserService
from off_key_tactic_middleware.services.catalogue.broker_check import BrokerCheck
from off_key_tactic_middleware.services.catalogue.system import SystemService
from off_key_tactic_middleware.services.catalogue.system_live import (
    SystemLiveService,
)
from off_key_tactic_middleware.services.data import (
    AlarmService,
    CatalogueDataService,
    FavoriteService,
)
from off_key_tactic_middleware.services.data.alarm_actions import AlarmActions
from off_key_tactic_middleware.services.dojo.datasets import DojoDatasets
from off_key_tactic_middleware.services.dojo.labels import DojoLabels
from off_key_tactic_middleware.services.dojo.metrics import DojoMetrics
from off_key_tactic_middleware.services.dojo.runs import DojoRuns
from off_key_tactic_middleware.services.orchestration.radar import (
    RadarOrchestrationService,
)
from off_key_tactic_middleware.services.pipelines.activation import (
    PipelineActivations,
)
from off_key_tactic_middleware.services.pipelines.blocks import PipelineBlocks
from off_key_tactic_middleware.services.pipelines.forms import start_form_monitor
from off_key_tactic_middleware.services.pipelines.library import PipelineLibrary
from off_key_tactic_middleware.services.pipelines.proposals import (
    PipelineProposals,
)
from sqlalchemy.ext.asyncio import AsyncSession

# One session per request, committed when the route returns and before the
# response is sent. FastAPI ends a dependency with the default scope only after
# the response, which answered a write before it was committed and let a read
# sent right after it see the old state.
RequestSession = Depends(get_db_async, scope="function")


def get_radar_orchestration_service(
    session: AsyncSession = RequestSession,
) -> RadarOrchestrationService:
    return RadarOrchestrationService(session)


def get_user_service(
    session: AsyncSession = RequestSession,
) -> UserService:
    """Dependency provider for user/account use cases."""
    return UserService(session, UserRepository(session))


def get_favorite_service(
    session: AsyncSession = RequestSession,
) -> FavoriteService:
    """Dependency provider for favorites use cases."""
    return FavoriteService(session, FavoriteRepository(session))


def get_alarm_service(
    session: AsyncSession = RequestSession,
) -> AlarmService:
    """Dependency provider for alarm use cases."""
    return AlarmService(session, AnomalyRepository(session))


async def get_catalogue_data_service(
    session: AsyncSession = RequestSession,
) -> CatalogueDataService:
    """Devices, measurements and evidence by catalogue id, resolved against the
    saved catalogue of this request."""
    return CatalogueDataService(session, await SystemService(session).read())


def get_alarm_actions(session: AsyncSession = RequestSession) -> AlarmActions:
    return AlarmActions(session)


def get_system_service(session: AsyncSession = RequestSession) -> SystemService:
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


def get_pipeline_library(
    session: AsyncSession = RequestSession,
) -> PipelineLibrary:
    return PipelineLibrary(session)


def get_pipeline_blocks(session: AsyncSession = RequestSession) -> PipelineBlocks:
    return PipelineBlocks(session)


def get_pipeline_proposals(
    session: AsyncSession = RequestSession,
) -> PipelineProposals:
    return PipelineProposals(session)


def get_dojo_datasets(session: AsyncSession = RequestSession) -> DojoDatasets:
    return DojoDatasets(session)


def get_dojo_runs(session: AsyncSession = RequestSession) -> DojoRuns:
    return DojoRuns(session)


def get_dojo_labels(session: AsyncSession = RequestSession) -> DojoLabels:
    return DojoLabels(session)


def get_dojo_metrics(session: AsyncSession = RequestSession) -> DojoMetrics:
    return DojoMetrics(session)


def get_pipeline_activations(
    session: AsyncSession = RequestSession,
) -> PipelineActivations:
    return PipelineActivations(session)


def get_form_monitor_starter(session: AsyncSession = RequestSession):
    """Start a setup-form monitor as its equivalent pipeline activation."""
    return partial(start_form_monitor, session)


def get_member_service(session: AsyncSession = RequestSession) -> MemberService:
    return MemberService(session)


def get_agent_service(session: AsyncSession = RequestSession) -> AgentService:
    return AgentService(session)


def get_remembered_session_service(
    session: AsyncSession = RequestSession,
) -> RememberedSessionService:
    return RememberedSessionService(session)
