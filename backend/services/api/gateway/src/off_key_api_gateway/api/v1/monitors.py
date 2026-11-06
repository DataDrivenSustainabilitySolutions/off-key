from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from off_key_core.schemas.pipelines import MonitorDetail, MonitorSummary
from off_key_core.schemas.radar import (
    FormMonitorConfig,
    MonitoringStrategy,
    RadarServiceLabel,
)
from pydantic import AliasChoices, BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

from ...facades.tactic import TacticError, tactic
from ..errors import TacticErrorRoute
from ..rate_limiter import limiter
from .pipelines import monitor_pipeline_router

router = APIRouter(route_class=TacticErrorRoute)
# Its /overview and /{monitor_id}/pipeline routes come before /{monitor_id}.
router.include_router(monitor_pipeline_router)

shared_limit_fetch = limiter.shared_limit("60/minute", scope="services")
shared_limit_execute = limiter.shared_limit("20/minute", scope="services")


def _normalize_models_for_gateway(
    models_from_tactic: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """
    Normalize TACTIC model list into gateway's existing dictionary response shape.

    Data source stays TACTIC; only the transport shape is adapted for consumers.
    """
    # TACTIC's ModelInfo always carries every field; nulls pass through unchanged.
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
        for model in models_from_tactic
    }


class MonitorCreate(FormMonitorConfig):
    """A monitor started from the setup form: what to watch and how."""

    container_name: SkipJsonSchema[str | None] = Field(default=None, exclude=True)  # ty: ignore[invalid-attribute-override]
    display_name: str = Field(min_length=1, max_length=120, strict=True)  # ty: ignore[invalid-attribute-override]
    # The gateway never forwards MQTT overrides, so the field is pinned to None.
    mqtt_config: SkipJsonSchema[None] = Field(default=None, exclude=True)  # ty: ignore[invalid-attribute-override]

    def form(self) -> FormMonitorConfig:
        return FormMonitorConfig.model_validate(
            self.model_dump(mode="json") | {"container_name": self.display_name}
        )


class MonitorStarted(BaseModel):
    """A monitor accepted for start; poll its activation until it settles."""

    monitor_id: str = Field(validation_alias=AliasChoices("monitor_id", "service_id"))
    activation_id: str
    phase: str = Field(validation_alias=AliasChoices("phase", "status"))
    mqtt_topics: list[str]


class MonitorName(BaseModel):
    id: str
    display_name: str


class MonitorStopped(BaseModel):
    monitor_id: str = Field(validation_alias=AliasChoices("monitor_id", "service_id"))
    status: Literal["stopped"]


@router.get("", response_model=list[MonitorSummary])
@shared_limit_fetch
async def list_monitors(request: Request, active: bool | None = None):
    """Every monitor with its state, strategy and the readings it watches.

    `active=true` keeps the monitors that should run, `active=false` the
    stopped ones.
    """
    monitors = await tactic.list_radar_services(active_only=active is True)
    if active is False:
        monitors = [item for item in monitors if not item.get("status")]
    return monitors


@router.post("", response_model=MonitorStarted, status_code=202)
@shared_limit_execute
async def create_monitor(request: Request, monitor: MonitorCreate):
    """Start a monitor from the setup form. Needs `manage_monitors`.

    TACTIC runs it as a pipeline. Answers 202 with the activation to poll at
    `GET /v1/pipeline-activations/{activation_id}`. A monitor designed as a
    graph starts with `POST /v1/pipelines/apply` instead.
    """
    return await tactic.start_radar_service(monitor.form())


@router.get("/{monitor_id}", response_model=MonitorDetail)
@shared_limit_fetch
async def get_monitor(request: Request, monitor_id: str):
    """One monitor with the configuration it was started with."""
    return await tactic.get_radar_service_details(monitor_id)


@router.patch("/{monitor_id}", response_model=MonitorName)
@shared_limit_execute
async def update_monitor(request: Request, monitor_id: str, change: RadarServiceLabel):
    """Change the name a monitor is shown with. Needs `manage_monitors`."""
    return await tactic.rename_radar_service(monitor_id, change.display_name)


@router.post("/{monitor_id}/stop", response_model=MonitorStopped)
@shared_limit_execute
async def stop_monitor(request: Request, monitor_id: str):
    """Stop a monitor and remove its workload. Needs `manage_monitors`.

    The monitor stays listed as stopped and its alarms stay in Reporting.
    """
    return await tactic.stop_radar_service(monitor_id)


@router.delete(
    "/{monitor_id}", status_code=204, response_class=Response, response_model=None
)
@shared_limit_execute
async def delete_monitor(request: Request, monitor_id: str):
    """Stop a monitor and delete it, releasing its readings. Needs `manage_monitors`.

    Its alarms stay in Reporting.
    """
    await tactic.delete_radar_service(monitor_id)
    return Response(status_code=204)


detectors_router = APIRouter(route_class=TacticErrorRoute)


@detectors_router.get("", response_model=dict[str, Any])
@shared_limit_fetch
async def list_detectors(
    request: Request,
    response: Response,
    strategy: MonitoringStrategy | None = Query(default=None),
):
    """Detector models with their family, cost and parameter JSON schema.

    Filter by `strategy`. Cacheable for five minutes.
    """
    # Enable client-side caching - models rarely change
    response.headers["Cache-Control"] = "public, max-age=300"
    try:
        models = await tactic.list_available_models(strategy)
        return _normalize_models_for_gateway(models)
    except TacticError:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get available models: {e!s}"
        ) from e
