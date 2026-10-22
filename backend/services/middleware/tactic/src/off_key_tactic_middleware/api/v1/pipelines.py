"""Member-authenticated monitoring design, activation and workspace endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from off_key_core.db.base import get_db_async
from off_key_core.db.models import MonitoringService
from off_key_core.models.pipeline_reports import bounded_validation_report
from off_key_core.models.pipelines import pipeline_catalog, validate_pipeline
from off_key_core.schemas.pipelines import (
    PipelineActivationRequest,
    PipelineActivationView,
    PipelineApplyRequest,
    PipelineCatalog,
    PipelineCreate,
    PipelineDraftSave,
    PipelineHistoryPage,
    PipelineHistoryQuery,
    PipelineLayout,
    PipelineListPage,
    PipelineListQuery,
    PipelineMetadataChange,
    PipelinePublish,
    PipelineRevisionPage,
    PipelineRevisionQuery,
    PipelineRevisionView,
    PipelineServiceView,
    PipelineValidateRequest,
    PipelineValidationReport,
    PipelineView,
    PipelineWorkspace,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ...config.config import get_tactic_settings
from ...provider import get_radar_orchestration_service
from ...services.pipelines.activation import PipelineActivations
from ...services.pipelines.library import PipelineLibrary
from ..collection_auth import current_member, require_admin
from ..errors import DomainErrorRoute

router = APIRouter(
    prefix="/monitors",
    dependencies=[Depends(current_member)],
    route_class=DomainErrorRoute,
)


@router.post(
    "/pipelines/apply",
    response_model=PipelineActivationView,
    status_code=202,
    dependencies=[Depends(require_admin)],
)
async def apply_pipeline(
    change: PipelineApplyRequest, session: AsyncSession = Depends(get_db_async)
):
    return await invoke(PipelineActivations(session).apply(change))


async def invoke(operation):
    try:
        return await operation
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/pipelines/catalog", response_model=PipelineCatalog)
async def catalog():
    return pipeline_catalog(get_tactic_settings().config.pipeline_authoring_enabled)


@router.get("/pipelines", response_model=PipelineListPage)
async def list_pipelines(
    query: Annotated[PipelineListQuery, Query()],
    session: AsyncSession = Depends(get_db_async),
):
    return await invoke(PipelineLibrary(session).list(query))


@router.post(
    "/pipelines",
    response_model=PipelineView,
    status_code=201,
    dependencies=[Depends(require_admin)],
)
async def create_pipeline(
    change: PipelineCreate, session: AsyncSession = Depends(get_db_async)
):
    return await invoke(PipelineLibrary(session).create(change))


@router.post(
    "/pipelines/validate",
    response_model=PipelineValidationReport,
    dependencies=[Depends(require_admin)],
)
async def validate_unsaved_design(change: PipelineValidateRequest):
    """Infer an unsaved workbench's features without creating a library record."""
    return bounded_validation_report(
        validate_pipeline(change.definition), change.selected_node_id
    )


@router.get("/pipelines/{pipeline_id}", response_model=PipelineView)
async def get_pipeline(pipeline_id: str, session: AsyncSession = Depends(get_db_async)):
    return await invoke(PipelineLibrary(session).get(pipeline_id))


@router.patch(
    "/pipelines/{pipeline_id}",
    response_model=PipelineView,
    dependencies=[Depends(require_admin)],
)
async def update_pipeline(
    pipeline_id: str,
    change: PipelineMetadataChange,
    session: AsyncSession = Depends(get_db_async),
):
    return await invoke(PipelineLibrary(session).metadata(pipeline_id, change))


@router.put(
    "/pipelines/{pipeline_id}/draft",
    response_model=PipelineView,
    dependencies=[Depends(require_admin)],
)
async def save_draft(
    pipeline_id: str,
    change: PipelineDraftSave,
    session: AsyncSession = Depends(get_db_async),
):
    return await invoke(PipelineLibrary(session).save_draft(pipeline_id, change))


@router.post(
    "/pipelines/{pipeline_id}/validate",
    response_model=PipelineValidationReport,
    dependencies=[Depends(require_admin)],
)
async def validate_draft(
    pipeline_id: str,
    change: PipelineValidateRequest,
    session: AsyncSession = Depends(get_db_async),
):
    return await invoke(
        PipelineLibrary(session).validate(
            pipeline_id, change.definition, change.selected_node_id
        )
    )


@router.get("/pipelines/{pipeline_id}/revisions", response_model=PipelineRevisionPage)
async def list_revisions(
    pipeline_id: str,
    query: Annotated[PipelineRevisionQuery, Query()],
    session: AsyncSession = Depends(get_db_async),
):
    return await invoke(PipelineLibrary(session).revisions(pipeline_id, query))


@router.post(
    "/pipelines/{pipeline_id}/revisions",
    response_model=PipelineRevisionView,
    status_code=201,
    dependencies=[Depends(require_admin)],
)
async def publish_revision(
    pipeline_id: str,
    change: PipelinePublish,
    session: AsyncSession = Depends(get_db_async),
):
    return await invoke(PipelineLibrary(session).publish(pipeline_id, change))


@router.get(
    "/pipelines/{pipeline_id}/revisions/{revision_id}",
    response_model=PipelineRevisionView,
)
async def get_revision(
    pipeline_id: str, revision_id: str, session: AsyncSession = Depends(get_db_async)
):
    return await invoke(PipelineLibrary(session).revision(pipeline_id, revision_id))


@router.get(
    "/pipelines/{pipeline_id}/revisions/{revision_id}/metadata",
    response_model=PipelineValidationReport,
)
async def revision_metadata(
    pipeline_id: str,
    revision_id: str,
    selected_node_id: str = Query(min_length=1, max_length=100),
    session: AsyncSession = Depends(get_db_async),
):
    return await invoke(
        PipelineLibrary(session).revision_metadata(
            pipeline_id, revision_id, selected_node_id
        )
    )


@router.post(
    "/pipeline-activations",
    response_model=PipelineActivationView,
    status_code=202,
    dependencies=[Depends(require_admin)],
)
async def activate_pipeline(
    change: PipelineActivationRequest,
    session: AsyncSession = Depends(get_db_async),
):
    return await invoke(PipelineActivations(session).submit(change))


@router.get(
    "/pipeline-activations/{activation_id}", response_model=PipelineActivationView
)
async def get_activation(
    activation_id: str, session: AsyncSession = Depends(get_db_async)
):
    return await invoke(PipelineActivations(session).get(activation_id))


@router.delete(
    "/pipeline-activations/{activation_id}",
    response_model=PipelineActivationView,
    dependencies=[Depends(require_admin)],
)
async def cancel_activation(
    activation_id: str, session: AsyncSession = Depends(get_db_async)
):
    return await invoke(PipelineActivations(session).cancel(activation_id))


@router.get("/workspace", response_model=PipelineWorkspace)
async def monitoring_workspace(
    selected_service_id: str | None = Query(default=None, max_length=100),
    session: AsyncSession = Depends(get_db_async),
    orchestration=Depends(get_radar_orchestration_service),
):
    services = await orchestration.list_radar_services(include_docker_status=False)
    state = None
    if selected_service_id:
        selected = await session.get(MonitoringService, selected_service_id)
        if selected is not None:
            state = (selected.operational_status or {}).get("pipeline_state")
    return PipelineWorkspace(
        services=services,
        authoring_enabled=get_tactic_settings().config.pipeline_authoring_enabled,
        selected_service_id=selected_service_id,
        pipeline_state=state,
    )


@router.get("/{service_id}/pipeline", response_model=PipelineServiceView)
async def service_pipeline(
    service_id: str,
    selected_node_id: str | None = Query(default=None, min_length=1, max_length=100),
    session: AsyncSession = Depends(get_db_async),
):
    return await invoke(PipelineLibrary(session).service(service_id, selected_node_id))


@router.get("/{service_id}/pipeline-history", response_model=PipelineHistoryPage)
async def service_history(
    service_id: str,
    query: Annotated[PipelineHistoryQuery, Query()],
    session: AsyncSession = Depends(get_db_async),
):
    return await invoke(PipelineLibrary(session).history(service_id, query))


@router.get("/{service_id}/pipeline-metadata", response_model=PipelineValidationReport)
async def service_metadata(
    service_id: str,
    selected_node_id: str = Query(min_length=1, max_length=100),
    session: AsyncSession = Depends(get_db_async),
):
    return await invoke(
        PipelineLibrary(session).service_metadata(service_id, selected_node_id)
    )


@router.get("/{service_id}/pipeline-state")
async def service_pipeline_state(
    service_id: str, session: AsyncSession = Depends(get_db_async)
):
    service = await session.get(MonitoringService, service_id)
    if service is None:
        raise HTTPException(404, "Monitoring service not found")
    return (service.operational_status or {}).get("pipeline_state")


@router.put(
    "/{service_id}/pipeline-layout",
    response_model=PipelineLayout,
    dependencies=[Depends(require_admin)],
)
async def service_pipeline_layout(
    service_id: str,
    layout: PipelineLayout,
    session: AsyncSession = Depends(get_db_async),
):
    return await invoke(PipelineLibrary(session).layout(service_id, layout))
