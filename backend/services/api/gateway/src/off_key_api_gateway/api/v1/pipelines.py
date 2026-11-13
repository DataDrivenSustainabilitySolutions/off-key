"""Typed member routes with independent polling, compiler and mutation budgets."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from off_key_core.schemas.forecast import ForecastModelInfo
from off_key_core.schemas.members import MemberProfile
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

from ...facades.tactic import path_segment, tactic
from ..access import current_member
from ..errors import TacticErrorRoute
from ..rate_limiter import client_ip, limiter


async def member_scope(
    request: Request, member: MemberProfile = Depends(current_member)
):
    request.state.pipeline_member_id = str(member.id)


def member_key(request: Request) -> str:
    if getattr(request.state, "demo_guest", False):
        return f"demo:{client_ip(request)}"
    return request.state.pipeline_member_id


def member_router() -> APIRouter:
    return APIRouter(dependencies=[Depends(member_scope)], route_class=TacticErrorRoute)


router = member_router()
components_router = member_router()
forecast_models_router = member_router()
blocks_router = member_router()
activations_router = member_router()
monitor_pipeline_router = member_router()
read_limit = limiter.shared_limit(
    "120/minute", scope="pipeline-reads", key_func=member_key
)
write_limit = limiter.shared_limit(
    "30/minute", scope="pipeline-writes", key_func=member_key
)
compile_limit = limiter.shared_limit(
    "120/minute", scope="pipeline-validation", key_func=member_key
)


async def forward(request, method, path, body=None, params=None):
    return await tactic.request(
        method,
        f"/api/v1/monitors{path}",
        json_data=body.model_dump(mode="json") if body is not None else None,
        params=params,
        headers={"Authorization": request.headers["Authorization"]},
    )


@router.post("/apply", response_model=PipelineActivationView, status_code=202)
@write_limit
async def apply_pipeline(request: Request, change: PipelineApplyRequest):
    """Start or replace a monitor from a design in one step. Needs `manage_monitors`.

    Saves the design, publishes a revision and activates it on the readings in
    `bindings` (input slot id to catalogue reading id). `replace_monitor_id`
    swaps out a running monitor. Repeating a request with the same
    `idempotency_key` returns the first activation instead of starting another.
    Answers 202: poll the activation until its `phase` settles.
    """
    return await forward(request, "POST", "/pipelines/apply", change)


@monitor_pipeline_router.get("/overview", response_model=PipelineWorkspace)
@read_limit
async def get_monitor_overview(
    request: Request, selected_monitor_id: str | None = None
):
    """What the Monitoring page loads: every monitor, whether designs may be
    edited, and the live pipeline state of `selected_monitor_id`.
    """
    return await forward(
        request,
        "GET",
        "/workspace",
        params={"selected_service_id": selected_monitor_id},
    )


@components_router.get("", response_model=PipelineCatalog)
@read_limit
async def list_pipeline_components(request: Request):
    """The components a design may use, with descriptions and parameter schemas,
    and the starting templates.
    """
    return await forward(request, "GET", "/pipelines/catalog")


@forecast_models_router.get("", response_model=ForecastModelCatalog)
@read_limit
async def list_forecast_models(request: Request):
    """The models of the deployment's forecast service, which pretrained
    forecaster steps use, each with its `status` (`not_downloaded`,
    `downloading` with `progress` from 0 to 1, `ready`, or `failed` with the
    `error`). `service` is `not_deployed` where the deployment has no forecast
    service, and `unreachable` while it does not answer; `models` is then empty.
    """
    return await forward(request, "GET", "/pipelines/forecast-models")


@forecast_models_router.post(
    "/downloads", response_model=ForecastModelInfo, status_code=202
)
@write_limit
async def download_forecast_model(request: Request, change: ForecastModelDownload):
    """Have the forecast service download a model's weights. Needs `manage_monitors`.

    Answers 202 at once with the model's state: poll the list for its progress.
    A model that is ready or already downloading is left as it is, and a failed
    download starts again. Answers 409 where the deployment has no forecast
    service, 404 for a model it does not offer, and 503 while it does not answer.
    """
    return await forward(
        request, "POST", "/pipelines/forecast-models/downloads", change
    )


@blocks_router.get("", response_model=PipelineBlockList)
@read_limit
async def list_pipeline_blocks(request: Request):
    """Every saved block, by name. A block is a chain of steps with their
    settings that the composer copies into a design.
    """
    return await forward(request, "GET", "/pipeline-blocks")


@blocks_router.post("", response_model=PipelineBlockView, status_code=201)
@write_limit
async def create_pipeline_block(request: Request, change: PipelineBlockCreate):
    """Save a chain of steps as a block. Needs `manage_monitors`.

    `steps` are in order, each feeding the next; a block holds only steps that
    take features and give features. Answers 409 for a name that is taken or
    once the library holds 100 blocks.
    """
    return await forward(request, "POST", "/pipeline-blocks", change)


@blocks_router.delete("/{block_id}", status_code=204)
@write_limit
async def delete_pipeline_block(request: Request, block_id: str):
    """Delete a block. Needs `manage_monitors`.

    Designs that copied its steps keep them.
    """
    await forward(request, "DELETE", f"/pipeline-blocks/{path_segment(block_id)}")
    return Response(status_code=204)


@router.get("", response_model=PipelineListPage)
@read_limit
async def list_pipelines(
    request: Request, query: Annotated[PipelineListQuery, Query()]
):
    """Saved designs, paged."""
    return await forward(
        request, "GET", "/pipelines", params=query.model_dump(exclude_none=True)
    )


@router.post("", response_model=PipelineView, status_code=201)
@write_limit
async def create_pipeline(request: Request, change: PipelineCreate):
    """Save a new design as a draft. Needs `manage_monitors`."""
    return await forward(request, "POST", "/pipelines", change)


@router.post("/validate", response_model=PipelineValidationReport)
@compile_limit
async def validate_unsaved_design(request: Request, change: PipelineValidateRequest):
    """Check a design without saving it: issues, and with `selected_node_id` the
    fields available at that node.
    """
    return await forward(request, "POST", "/pipelines/validate", change)


@router.get("/{pipeline_id}", response_model=PipelineView)
@read_limit
async def get_pipeline(request: Request, pipeline_id: str):
    """One design with its draft graph, its `version` and its revisions."""
    return await forward(request, "GET", f"/pipelines/{path_segment(pipeline_id)}")


@router.patch("/{pipeline_id}", response_model=PipelineView)
@write_limit
async def update_pipeline(
    request: Request, pipeline_id: str, change: PipelineMetadataChange
):
    """Rename, describe or archive a design. Needs `manage_monitors`.

    Send the current `expected_version`; a stale one answers 409.
    """
    return await forward(
        request, "PATCH", f"/pipelines/{path_segment(pipeline_id)}", change
    )


@router.put("/{pipeline_id}/draft", response_model=PipelineView)
@write_limit
async def save_draft(request: Request, pipeline_id: str, change: PipelineDraftSave):
    """Replace a design's draft graph and layout. Needs `manage_monitors`.

    Send the current `expected_version`; a stale one answers 409.
    """
    return await forward(
        request, "PUT", f"/pipelines/{path_segment(pipeline_id)}/draft", change
    )


@router.post("/{pipeline_id}/validate", response_model=PipelineValidationReport)
@compile_limit
async def validate_pipeline(
    request: Request, pipeline_id: str, change: PipelineValidateRequest
):
    """Check a graph against a saved design without saving it."""
    return await forward(
        request, "POST", f"/pipelines/{path_segment(pipeline_id)}/validate", change
    )


@router.get("/{pipeline_id}/revisions", response_model=PipelineRevisionPage)
@read_limit
async def list_pipeline_revisions(
    request: Request,
    pipeline_id: str,
    query: Annotated[PipelineRevisionQuery, Query()],
):
    """Published revisions of a design, newest first, paged by `next_before`."""
    return await forward(
        request,
        "GET",
        f"/pipelines/{path_segment(pipeline_id)}/revisions",
        params=query.model_dump(exclude_none=True),
    )


@router.post(
    "/{pipeline_id}/revisions",
    response_model=PipelineRevisionView,
    status_code=201,
)
@write_limit
async def publish_revision(request: Request, pipeline_id: str, change: PipelinePublish):
    """Freeze the current draft as a new revision that monitors can run.

    Needs `manage_monitors`. Send the current `expected_version`.
    """
    return await forward(
        request, "POST", f"/pipelines/{path_segment(pipeline_id)}/revisions", change
    )


@router.get(
    "/{pipeline_id}/revisions/{revision_id}",
    response_model=PipelineRevisionView,
)
@read_limit
async def get_revision(request: Request, pipeline_id: str, revision_id: str):
    """One published revision with its graph and fingerprint."""
    return await forward(
        request,
        "GET",
        f"/pipelines/{path_segment(pipeline_id)}/revisions/{path_segment(revision_id)}",
    )


@router.get(
    "/{pipeline_id}/revisions/{revision_id}/metadata",
    response_model=PipelineValidationReport,
)
@compile_limit
async def get_revision_metadata(
    request: Request,
    pipeline_id: str,
    revision_id: str,
    selected_node_id: str = Query(min_length=1, max_length=100),
):
    """Validation of a published revision, with the fields available at
    `selected_node_id`.
    """
    return await forward(
        request,
        "GET",
        f"/pipelines/{path_segment(pipeline_id)}/revisions/{path_segment(revision_id)}/metadata",
        params={"selected_node_id": selected_node_id},
    )


@activations_router.post("", response_model=PipelineActivationView, status_code=202)
@write_limit
async def activate_pipeline(request: Request, change: PipelineActivationRequest):
    """Run a published revision as a monitor. Needs `manage_monitors`.

    `bindings` maps each input slot to a catalogue reading id. Answers 202 with
    an activation: poll it until its `phase` is `succeeded`, `failed` or
    `cancelled`. Repeating a request with the same `idempotency_key` returns the
    first activation instead of starting another.
    """
    return await forward(request, "POST", "/pipeline-activations", change)


@activations_router.get("/{activation_id}", response_model=PipelineActivationView)
@read_limit
async def get_activation(request: Request, activation_id: str):
    """Progress of an activation: its `phase`, the monitor it starts and any issues."""
    return await forward(
        request, "GET", f"/pipeline-activations/{path_segment(activation_id)}"
    )


@activations_router.post(
    "/{activation_id}/cancel", response_model=PipelineActivationView
)
@write_limit
async def cancel_activation(request: Request, activation_id: str):
    """Cancel an activation that has not finished. Needs `manage_monitors`."""
    return await forward(
        request, "DELETE", f"/pipeline-activations/{path_segment(activation_id)}"
    )


@monitor_pipeline_router.get(
    "/{monitor_id}/pipeline", response_model=PipelineServiceView
)
@read_limit
async def get_monitor_pipeline(
    request: Request,
    monitor_id: str,
    selected_node_id: str | None = Query(default=None, min_length=1, max_length=100),
):
    """The design a monitor runs, its current run, recent run history and
    validation, optionally for `selected_node_id`.
    """
    return await forward(
        request,
        "GET",
        f"/{path_segment(monitor_id)}/pipeline",
        params={"selected_node_id": selected_node_id} if selected_node_id else None,
    )


@monitor_pipeline_router.get(
    "/{monitor_id}/pipeline/history", response_model=PipelineHistoryPage
)
@read_limit
async def list_monitor_pipeline_history(
    request: Request,
    monitor_id: str,
    query: Annotated[PipelineHistoryQuery, Query()],
):
    """Earlier runs this monitor replaced, most recent first. For the next page
    ask for the history of `next_monitor_id`.
    """
    return await forward(
        request,
        "GET",
        f"/{path_segment(monitor_id)}/pipeline-history",
        params=query.model_dump(exclude_none=True),
    )


@monitor_pipeline_router.get(
    "/{monitor_id}/pipeline/timeline", response_model=PipelineRunTimeline
)
@read_limit
async def get_monitor_pipeline_timeline(request: Request, monitor_id: str):
    """What a monitor's run went through, oldest event first, and how it ended."""
    return await forward(
        request, "GET", f"/{path_segment(monitor_id)}/pipeline-timeline"
    )


@monitor_pipeline_router.get(
    "/{monitor_id}/pipeline/metadata", response_model=PipelineValidationReport
)
@compile_limit
async def get_monitor_pipeline_metadata(
    request: Request,
    monitor_id: str,
    selected_node_id: str = Query(min_length=1, max_length=100),
):
    """Validation of a monitor's design, with the fields available at
    `selected_node_id`.
    """
    return await forward(
        request,
        "GET",
        f"/{path_segment(monitor_id)}/pipeline-metadata",
        params={"selected_node_id": selected_node_id},
    )


@monitor_pipeline_router.get("/{monitor_id}/pipeline/state")
@read_limit
async def get_monitor_pipeline_state(request: Request, monitor_id: str):
    """The diagnostic snapshot a running monitor last reported for its nodes."""
    return await forward(request, "GET", f"/{path_segment(monitor_id)}/pipeline-state")


@monitor_pipeline_router.put(
    "/{monitor_id}/pipeline/layout", response_model=PipelineLayout
)
@write_limit
async def save_monitor_pipeline_layout(
    request: Request, monitor_id: str, layout: PipelineLayout
):
    """Store where a monitor's nodes sit on the canvas; the graph is unchanged.

    Needs `manage_monitors`.
    """
    return await forward(
        request, "PUT", f"/{path_segment(monitor_id)}/pipeline-layout", layout
    )
