from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from off_key_core.auth.agents import OPEN_TO_AGENTS
from off_key_core.schemas.pipelines import (
    ComponentField,
    MonitorDetail,
    MonitorSummary,
)
from off_key_core.schemas.radar import (
    MonitoringStrategy,
    MonitorSetup,
    RadarServiceLabel,
)
from off_key_tactic_middleware.models.catalog import available_models
from off_key_tactic_middleware.services.orchestration.radar import (
    RadarOrchestrationService,
)
from pydantic import BaseModel

from ...providers import get_form_monitor_starter, get_radar_orchestration_service
from ..errors import DomainErrorRoute
from ..rate_limiter import limiter
from .pipelines import monitor_pipeline_router

router = APIRouter(route_class=DomainErrorRoute)
# Its /overview and /{monitor_id}/pipeline routes come before /{monitor_id}.
router.include_router(monitor_pipeline_router)

shared_limit_fetch = limiter.shared_limit("60/minute", scope="services")
shared_limit_execute = limiter.shared_limit("20/minute", scope="services")


class ModelInfo(BaseModel):
    """One detector of the catalogue, with every field present."""

    model_type: str
    family: str
    name: str
    description: str | None = None
    complexity: str | None = None
    memory_usage: str | None = None
    strategy: str = "static_baseline"
    catalog_id: str | None = None
    algorithm_family: str | None = None
    available: bool = True
    fields: list[ComponentField]
    default_capabilities: dict[str, Any] | None = None
    import_paths: list[str]
    parameter_schema: dict[str, Any]
    default_parameters: dict[str, Any]
    version: str
    requires_special_handling: bool


def detectors_by_type(strategy: str | None = None) -> dict[str, dict[str, Any]]:
    """The detector catalogue keyed by model type, as the setup forms read it."""
    models = [
        ModelInfo(**model).model_dump(mode="json") for model in available_models()
    ]
    return {
        model["model_type"]: {
            "name": model["name"],
            "description": model["description"],
            "family": model["family"],
            "strategy": model["strategy"],
            "complexity": model["complexity"],
            "memory_usage": model["memory_usage"],
            "parameters": model["parameter_schema"],
            "fields": model["fields"],
            "default_parameters": model["default_parameters"],
            "version": model["version"],
            "requires_special_handling": model["requires_special_handling"],
            "catalog_id": model["catalog_id"],
            "algorithm_family": model["algorithm_family"],
            "available": model["available"],
            "default_capabilities": model["default_capabilities"],
        }
        for model in models
        if not strategy or model["strategy"] == strategy
    }


class MonitorStarted(BaseModel):
    """A monitor accepted for start; poll its activation until it settles."""

    monitor_id: str
    activation_id: str
    phase: str
    reading_ids: list[str]


class MonitorName(BaseModel):
    id: str
    display_name: str


class MonitorStopped(BaseModel):
    monitor_id: str
    status: Literal["stopped"]


@router.get("", response_model=list[MonitorSummary], openapi_extra=OPEN_TO_AGENTS)
@shared_limit_fetch
async def list_monitors(
    request: Request,
    active: bool | None = None,
    service: RadarOrchestrationService = Depends(get_radar_orchestration_service),
):
    """Every monitor with its state, strategy and the readings it watches.

    `active=true` keeps the monitors that should run, `active=false` the
    stopped ones.
    """
    monitors = await service.list_radar_services(active is True, False)
    if active is False:
        monitors = [item for item in monitors if not item.get("status")]
    return monitors


@router.post("", response_model=MonitorStarted, status_code=202)
@shared_limit_execute
async def create_monitor(
    request: Request,
    monitor: MonitorSetup,
    start_form_monitor=Depends(get_form_monitor_starter),
):
    """Start a monitor on catalogue readings. Needs `manage_monitors`.

    `reading_ids` are recorded numeric readings of one device, or broker
    readings without a device; `monitoring` is the strategy and its detector.
    It runs as a pipeline activation. Answers 202 with the activation to poll at
    `GET /v1/pipeline-activations/{activation_id}`. A monitor designed as a
    graph starts with `POST /v1/pipelines/apply` instead.
    """
    activation = await start_form_monitor(monitor)
    return MonitorStarted(
        monitor_id=activation.service_id,
        activation_id=activation.id,
        phase=activation.phase,
        reading_ids=monitor.reading_ids,
    )


@router.get("/{monitor_id}", response_model=MonitorDetail, openapi_extra=OPEN_TO_AGENTS)
@shared_limit_fetch
async def get_monitor(
    request: Request,
    monitor_id: str,
    service: RadarOrchestrationService = Depends(get_radar_orchestration_service),
):
    """One monitor with the configuration it was started with."""
    detail = await service.get_radar_service(monitor_id)
    if not detail:
        raise HTTPException(404, "RADAR service not found")
    return detail


@router.patch("/{monitor_id}", response_model=MonitorName)
@shared_limit_execute
async def update_monitor(
    request: Request,
    monitor_id: str,
    change: RadarServiceLabel,
    service: RadarOrchestrationService = Depends(get_radar_orchestration_service),
):
    """Change the name a monitor is shown with. Needs `manage_monitors`."""
    if not await service.rename_radar_service(monitor_id, change.display_name):
        raise HTTPException(404, "Monitoring service not found")
    return MonitorName(id=monitor_id, display_name=change.display_name)


@router.post("/{monitor_id}/stop", response_model=MonitorStopped)
@shared_limit_execute
async def stop_monitor(
    request: Request,
    monitor_id: str,
    service: RadarOrchestrationService = Depends(get_radar_orchestration_service),
):
    """Stop a monitor and remove its workload. Needs `manage_monitors`.

    The monitor stays listed as stopped and its alarms stay in Reporting.
    """
    if not await service.stop_radar_service(monitor_id):
        raise HTTPException(
            404, f"RADAR service '{monitor_id}' was not found or not stopped"
        )
    return MonitorStopped(monitor_id=monitor_id, status="stopped")


@router.delete(
    "/{monitor_id}", status_code=204, response_class=Response, response_model=None
)
@shared_limit_execute
async def delete_monitor(
    request: Request,
    monitor_id: str,
    service: RadarOrchestrationService = Depends(get_radar_orchestration_service),
):
    """Stop a monitor and delete it, releasing its readings. Needs `manage_monitors`.

    Its alarms stay in Reporting.
    """
    if not await service.delete_radar_service(monitor_id):
        raise HTTPException(
            404, f"RADAR service '{monitor_id}' not found or could not be deleted"
        )
    return Response(status_code=204)


detectors_router = APIRouter(route_class=DomainErrorRoute)


@detectors_router.get("", response_model=dict[str, Any], openapi_extra=OPEN_TO_AGENTS)
@shared_limit_fetch
async def list_detectors(
    request: Request,
    response: Response,
    strategy: MonitoringStrategy | None = Query(default=None),
):
    """Detector models with their family, cost and parameter JSON schema.

    Filter by `strategy`. Cacheable for five minutes.
    """
    # The catalogue ships with the release, so clients may cache it.
    response.headers["Cache-Control"] = "public, max-age=300"
    return detectors_by_type(strategy)
