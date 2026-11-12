"""Member-authenticated monitoring design, activation and workspace endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from off_key_core.auth.permissions import Permission
from off_key_core.models.pipeline_reports import bounded_validation_report
from off_key_core.models.pipelines import pipeline_catalog, validate_pipeline
from off_key_core.schemas.forecast import ForecastModelInfo
from off_key_core.schemas.pipelines import (
    ForecastModelCatalog,
    ForecastModelDownload,
    PipelineActivationRequest,
    PipelineActivationView,
    PipelineApplyRequest,
    PipelineBlockCreate,
    PipelineBlockList,
    PipelineBlockView,
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
    PipelineRunTimeline,
    PipelineServiceView,
    PipelineValidateRequest,
    PipelineValidationReport,
    PipelineView,
    PipelineWorkspace,
)

from ...config.config import get_tactic_settings
from ...provider import (
    get_pipeline_activations,
    get_pipeline_blocks,
    get_pipeline_library,
)
from ...services.pipelines import forecast_models
from ...services.pipelines.activation import PipelineActivations
from ...services.pipelines.blocks import PipelineBlocks
from ...services.pipelines.library import PipelineLibrary
from ..collection_auth import current_member, require_permission
from ..errors import DomainErrorRoute

manage_monitors = require_permission(Permission.manage_monitors)
router = APIRouter(
    prefix="/monitors",
    dependencies=[Depends(current_member)],
    route_class=DomainErrorRoute,
)


@router.post(
    "/pipelines/apply",
    response_model=PipelineActivationView,
    status_code=202,
    dependencies=[Depends(manage_monitors)],
)
async def apply_pipeline(
    change: PipelineApplyRequest,
    activations: PipelineActivations = Depends(get_pipeline_activations),
):
    return await invoke(activations.apply(change))


async def invoke(operation):
    try:
        return await operation
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/pipelines/catalog", response_model=PipelineCatalog)
async def catalog():
    return pipeline_catalog(get_tactic_settings().config.pipeline_authoring_enabled)


@router.get("/pipelines/forecast-models", response_model=ForecastModelCatalog)
async def list_forecast_models():
    """The forecast service's checkpoints and whether each is downloaded."""
    return await run_in_threadpool(forecast_models.forecast_models)


@router.post(
    "/pipelines/forecast-models/downloads",
    response_model=ForecastModelInfo,
    status_code=202,
    dependencies=[Depends(manage_monitors)],
)
async def download_forecast_model(change: ForecastModelDownload):
    """Have the forecast service download a checkpoint; it answers at once."""
    try:
        return await run_in_threadpool(forecast_models.request_download, change.model)
    except forecast_models.ForecastServiceUnreachable as exc:
        raise HTTPException(
            503, "The forecast service does not answer. Try again shortly."
        ) from exc


@router.get("/pipelines", response_model=PipelineListPage)
async def list_pipelines(
    query: Annotated[PipelineListQuery, Query()],
    library: PipelineLibrary = Depends(get_pipeline_library),
):
    return await invoke(library.list(query))


@router.post(
    "/pipelines",
    response_model=PipelineView,
    status_code=201,
    dependencies=[Depends(manage_monitors)],
)
async def create_pipeline(
    change: PipelineCreate, library: PipelineLibrary = Depends(get_pipeline_library)
):
    return await invoke(library.create(change))


@router.post(
    "/pipelines/validate",
    response_model=PipelineValidationReport,
    dependencies=[Depends(manage_monitors)],
)
async def validate_unsaved_design(change: PipelineValidateRequest):
    """Infer an unsaved workbench's features without creating a library record."""
    return bounded_validation_report(
        validate_pipeline(change.definition), change.selected_node_id
    )


@router.get("/pipelines/{pipeline_id}", response_model=PipelineView)
async def get_pipeline(
    pipeline_id: str, library: PipelineLibrary = Depends(get_pipeline_library)
):
    return await invoke(library.get(pipeline_id))


@router.patch(
    "/pipelines/{pipeline_id}",
    response_model=PipelineView,
    dependencies=[Depends(manage_monitors)],
)
async def update_pipeline(
    pipeline_id: str,
    change: PipelineMetadataChange,
    library: PipelineLibrary = Depends(get_pipeline_library),
):
    return await invoke(library.metadata(pipeline_id, change))


@router.put(
    "/pipelines/{pipeline_id}/draft",
    response_model=PipelineView,
    dependencies=[Depends(manage_monitors)],
)
async def save_draft(
    pipeline_id: str,
    change: PipelineDraftSave,
    library: PipelineLibrary = Depends(get_pipeline_library),
):
    return await invoke(library.save_draft(pipeline_id, change))


@router.post(
    "/pipelines/{pipeline_id}/validate",
    response_model=PipelineValidationReport,
    dependencies=[Depends(manage_monitors)],
)
async def validate_draft(
    pipeline_id: str,
    change: PipelineValidateRequest,
    library: PipelineLibrary = Depends(get_pipeline_library),
):
    return await invoke(
        library.validate(pipeline_id, change.definition, change.selected_node_id)
    )


@router.get("/pipelines/{pipeline_id}/revisions", response_model=PipelineRevisionPage)
async def list_revisions(
    pipeline_id: str,
    query: Annotated[PipelineRevisionQuery, Query()],
    library: PipelineLibrary = Depends(get_pipeline_library),
):
    return await invoke(library.revisions(pipeline_id, query))


@router.post(
    "/pipelines/{pipeline_id}/revisions",
    response_model=PipelineRevisionView,
    status_code=201,
    dependencies=[Depends(manage_monitors)],
)
async def publish_revision(
    pipeline_id: str,
    change: PipelinePublish,
    library: PipelineLibrary = Depends(get_pipeline_library),
):
    return await invoke(library.publish(pipeline_id, change))


@router.get(
    "/pipelines/{pipeline_id}/revisions/{revision_id}",
    response_model=PipelineRevisionView,
)
async def get_revision(
    pipeline_id: str,
    revision_id: str,
    library: PipelineLibrary = Depends(get_pipeline_library),
):
    return await invoke(library.revision(pipeline_id, revision_id))


@router.get(
    "/pipelines/{pipeline_id}/revisions/{revision_id}/metadata",
    response_model=PipelineValidationReport,
)
async def revision_metadata(
    pipeline_id: str,
    revision_id: str,
    selected_node_id: str = Query(min_length=1, max_length=100),
    library: PipelineLibrary = Depends(get_pipeline_library),
):
    return await invoke(
        library.revision_metadata(pipeline_id, revision_id, selected_node_id)
    )


@router.post(
    "/pipeline-activations",
    response_model=PipelineActivationView,
    status_code=202,
    dependencies=[Depends(manage_monitors)],
)
async def activate_pipeline(
    change: PipelineActivationRequest,
    activations: PipelineActivations = Depends(get_pipeline_activations),
):
    return await invoke(activations.submit(change))


@router.get(
    "/pipeline-activations/{activation_id}", response_model=PipelineActivationView
)
async def get_activation(
    activation_id: str,
    activations: PipelineActivations = Depends(get_pipeline_activations),
):
    return await invoke(activations.get(activation_id))


@router.delete(
    "/pipeline-activations/{activation_id}",
    response_model=PipelineActivationView,
    dependencies=[Depends(manage_monitors)],
)
async def cancel_activation(
    activation_id: str,
    activations: PipelineActivations = Depends(get_pipeline_activations),
):
    return await invoke(activations.cancel(activation_id))


@router.get("/pipeline-blocks", response_model=PipelineBlockList)
async def list_blocks(blocks: PipelineBlocks = Depends(get_pipeline_blocks)):
    return await blocks.list()


@router.post(
    "/pipeline-blocks",
    response_model=PipelineBlockView,
    status_code=201,
    dependencies=[Depends(manage_monitors)],
)
async def create_block(
    change: PipelineBlockCreate, blocks: PipelineBlocks = Depends(get_pipeline_blocks)
):
    return await invoke(blocks.create(change))


@router.delete(
    "/pipeline-blocks/{block_id}",
    status_code=204,
    dependencies=[Depends(manage_monitors)],
)
async def delete_block(
    block_id: str, blocks: PipelineBlocks = Depends(get_pipeline_blocks)
):
    await blocks.remove(block_id)


@router.get("/workspace", response_model=PipelineWorkspace)
async def monitoring_workspace(
    selected_service_id: str | None = Query(default=None, max_length=100),
    library: PipelineLibrary = Depends(get_pipeline_library),
):
    return await library.workspace(selected_service_id)


@router.get("/{service_id}/pipeline", response_model=PipelineServiceView)
async def service_pipeline(
    service_id: str,
    selected_node_id: str | None = Query(default=None, min_length=1, max_length=100),
    library: PipelineLibrary = Depends(get_pipeline_library),
):
    return await invoke(library.service(service_id, selected_node_id))


@router.get("/{service_id}/pipeline-history", response_model=PipelineHistoryPage)
async def service_history(
    service_id: str,
    query: Annotated[PipelineHistoryQuery, Query()],
    library: PipelineLibrary = Depends(get_pipeline_library),
):
    return await invoke(library.history(service_id, query))


@router.get("/{service_id}/pipeline-timeline", response_model=PipelineRunTimeline)
async def service_timeline(
    service_id: str, library: PipelineLibrary = Depends(get_pipeline_library)
):
    return await invoke(library.timeline(service_id))


@router.get("/{service_id}/pipeline-metadata", response_model=PipelineValidationReport)
async def service_metadata(
    service_id: str,
    selected_node_id: str = Query(min_length=1, max_length=100),
    library: PipelineLibrary = Depends(get_pipeline_library),
):
    return await invoke(library.service_metadata(service_id, selected_node_id))


@router.get("/{service_id}/pipeline-state")
async def service_pipeline_state(
    service_id: str, library: PipelineLibrary = Depends(get_pipeline_library)
):
    return await invoke(library.pipeline_state(service_id))


@router.put(
    "/{service_id}/pipeline-layout",
    response_model=PipelineLayout,
    dependencies=[Depends(manage_monitors)],
)
async def service_pipeline_layout(
    service_id: str,
    layout: PipelineLayout,
    library: PipelineLibrary = Depends(get_pipeline_library),
):
    return await invoke(library.layout(service_id, layout))
