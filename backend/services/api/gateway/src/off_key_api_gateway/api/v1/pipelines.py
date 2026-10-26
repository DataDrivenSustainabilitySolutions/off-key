"""Typed member routes with independent polling, compiler and mutation budgets."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from off_key_core.schemas.members import MemberProfile
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

from ...facades.tactic import path_segment, tactic
from ..access import current_member
from ..errors import TacticErrorRoute
from ..rate_limiter import client_ip, limiter


async def member_scope(
    request: Request, member: MemberProfile = Depends(current_member)
):
    # Demo guests share one viewer member, so each visitor gets its own budget.
    request.state.pipeline_member_id = (
        f"guest:{client_ip(request)}"
        if getattr(request.state, "demo_guest", False)
        else str(member.id)
    )


def member_key(request: Request) -> str:
    return request.state.pipeline_member_id


router = APIRouter(dependencies=[Depends(member_scope)], route_class=TacticErrorRoute)
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


@router.post("/pipelines/apply", response_model=PipelineActivationView, status_code=202)
@write_limit
async def apply_pipeline(request: Request, change: PipelineApplyRequest):
    return await forward(request, "POST", "/pipelines/apply", change)


@router.get("/workspace", response_model=PipelineWorkspace)
@read_limit
async def monitoring_workspace(
    request: Request, selected_service_id: str | None = None
):
    return await forward(
        request,
        "GET",
        "/workspace",
        params={"selected_service_id": selected_service_id},
    )


@router.get("/pipelines/catalog", response_model=PipelineCatalog)
@read_limit
async def pipeline_catalog(request: Request):
    return await forward(request, "GET", "/pipelines/catalog")


@router.get("/pipelines", response_model=PipelineListPage)
@read_limit
async def list_pipelines(
    request: Request, query: Annotated[PipelineListQuery, Query()]
):
    return await forward(
        request, "GET", "/pipelines", params=query.model_dump(exclude_none=True)
    )


@router.post("/pipelines", response_model=PipelineView, status_code=201)
@write_limit
async def create_pipeline(request: Request, change: PipelineCreate):
    return await forward(request, "POST", "/pipelines", change)


@router.post("/pipelines/validate", response_model=PipelineValidationReport)
@compile_limit
async def validate_unsaved_design(request: Request, change: PipelineValidateRequest):
    return await forward(request, "POST", "/pipelines/validate", change)


@router.get("/pipelines/{pipeline_id}", response_model=PipelineView)
@read_limit
async def get_pipeline(request: Request, pipeline_id: str):
    return await forward(request, "GET", f"/pipelines/{path_segment(pipeline_id)}")


@router.patch("/pipelines/{pipeline_id}", response_model=PipelineView)
@write_limit
async def update_pipeline(
    request: Request, pipeline_id: str, change: PipelineMetadataChange
):
    return await forward(
        request, "PATCH", f"/pipelines/{path_segment(pipeline_id)}", change
    )


@router.put("/pipelines/{pipeline_id}/draft", response_model=PipelineView)
@write_limit
async def save_draft(request: Request, pipeline_id: str, change: PipelineDraftSave):
    return await forward(
        request, "PUT", f"/pipelines/{path_segment(pipeline_id)}/draft", change
    )


@router.post(
    "/pipelines/{pipeline_id}/validate", response_model=PipelineValidationReport
)
@compile_limit
async def validate_pipeline(
    request: Request, pipeline_id: str, change: PipelineValidateRequest
):
    return await forward(
        request, "POST", f"/pipelines/{path_segment(pipeline_id)}/validate", change
    )


@router.get("/pipelines/{pipeline_id}/revisions", response_model=PipelineRevisionPage)
@read_limit
async def list_revisions(
    request: Request,
    pipeline_id: str,
    query: Annotated[PipelineRevisionQuery, Query()],
):
    return await forward(
        request,
        "GET",
        f"/pipelines/{path_segment(pipeline_id)}/revisions",
        params=query.model_dump(exclude_none=True),
    )


@router.post(
    "/pipelines/{pipeline_id}/revisions",
    response_model=PipelineRevisionView,
    status_code=201,
)
@write_limit
async def publish_revision(request: Request, pipeline_id: str, change: PipelinePublish):
    return await forward(
        request, "POST", f"/pipelines/{path_segment(pipeline_id)}/revisions", change
    )


@router.get(
    "/pipelines/{pipeline_id}/revisions/{revision_id}",
    response_model=PipelineRevisionView,
)
@read_limit
async def get_revision(request: Request, pipeline_id: str, revision_id: str):
    return await forward(
        request,
        "GET",
        f"/pipelines/{path_segment(pipeline_id)}/revisions/{path_segment(revision_id)}",
    )


@router.get(
    "/pipelines/{pipeline_id}/revisions/{revision_id}/metadata",
    response_model=PipelineValidationReport,
)
@compile_limit
async def revision_metadata(
    request: Request,
    pipeline_id: str,
    revision_id: str,
    selected_node_id: str = Query(min_length=1, max_length=100),
):
    return await forward(
        request,
        "GET",
        f"/pipelines/{path_segment(pipeline_id)}/revisions/{path_segment(revision_id)}/metadata",
        params={"selected_node_id": selected_node_id},
    )


@router.post(
    "/pipeline-activations", response_model=PipelineActivationView, status_code=202
)
@write_limit
async def activate_pipeline(request: Request, change: PipelineActivationRequest):
    return await forward(request, "POST", "/pipeline-activations", change)


@router.get(
    "/pipeline-activations/{activation_id}", response_model=PipelineActivationView
)
@read_limit
async def get_activation(request: Request, activation_id: str):
    return await forward(
        request, "GET", f"/pipeline-activations/{path_segment(activation_id)}"
    )


@router.delete(
    "/pipeline-activations/{activation_id}", response_model=PipelineActivationView
)
@write_limit
async def cancel_activation(request: Request, activation_id: str):
    return await forward(
        request, "DELETE", f"/pipeline-activations/{path_segment(activation_id)}"
    )


@router.get("/{service_id}/pipeline", response_model=PipelineServiceView)
@read_limit
async def service_pipeline(
    request: Request,
    service_id: str,
    selected_node_id: str | None = Query(default=None, min_length=1, max_length=100),
):
    return await forward(
        request,
        "GET",
        f"/{path_segment(service_id)}/pipeline",
        params={"selected_node_id": selected_node_id} if selected_node_id else None,
    )


@router.get("/{service_id}/pipeline-history", response_model=PipelineHistoryPage)
@read_limit
async def service_history(
    request: Request,
    service_id: str,
    query: Annotated[PipelineHistoryQuery, Query()],
):
    return await forward(
        request,
        "GET",
        f"/{path_segment(service_id)}/pipeline-history",
        params=query.model_dump(exclude_none=True),
    )


@router.get("/{service_id}/pipeline-metadata", response_model=PipelineValidationReport)
@compile_limit
async def service_metadata(
    request: Request,
    service_id: str,
    selected_node_id: str = Query(min_length=1, max_length=100),
):
    return await forward(
        request,
        "GET",
        f"/{path_segment(service_id)}/pipeline-metadata",
        params={"selected_node_id": selected_node_id},
    )


@router.get("/{service_id}/pipeline-state")
@read_limit
async def pipeline_state(request: Request, service_id: str):
    return await forward(request, "GET", f"/{path_segment(service_id)}/pipeline-state")


@router.put("/{service_id}/pipeline-layout", response_model=PipelineLayout)
@write_limit
async def save_pipeline_layout(
    request: Request, service_id: str, layout: PipelineLayout
):
    return await forward(
        request, "PUT", f"/{path_segment(service_id)}/pipeline-layout", layout
    )
