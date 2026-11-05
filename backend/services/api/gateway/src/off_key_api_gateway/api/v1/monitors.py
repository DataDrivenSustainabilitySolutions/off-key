from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from off_key_core.schemas.radar import (
    FormMonitorConfig,
    MonitoringStrategy,
    RadarServiceLabel,
)
from off_key_core.utils.timestamps import as_utc
from pydantic import BaseModel, Field

from ...facades.tactic import TacticError, tactic
from ..errors import TacticErrorRoute
from ..rate_limiter import limiter
from .pipelines import router as pipeline_router

router = APIRouter(route_class=TacticErrorRoute)
router.include_router(pipeline_router)

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


class MonitoringServiceConfig(FormMonitorConfig):
    service_type: Literal["radar"] = Field(default="radar", exclude=True)
    # The gateway never forwards MQTT overrides, so the field is pinned to None.
    mqtt_config: None = Field(default=None, exclude=True)  # ty: ignore[invalid-attribute-override]


class ServiceResponse(BaseModel):
    service_id: str
    activation_id: str
    container_name: str
    status: str
    mqtt_topics: list[str]


def _require_one_container(container_name: str | None, container_id: str | None):
    if not container_name and not container_id:
        raise HTTPException(
            status_code=400,
            detail="You must provide either container_name or container_id.",
        )
    if container_name and container_id:
        raise HTTPException(
            status_code=400,
            detail="Provide only one of container_name or container_id.",
        )


@router.get("/all", response_model=list[dict[str, Any]])
@shared_limit_fetch
async def list_services(
    request: Request,
    active_only: bool = False,
    include_docker_status: bool = False,
):
    """Every monitor with its state, strategy and the MQTT topics it reads.

    `active_only` keeps running monitors. `include_docker_status` also asks
    each container for its status (`running`, `complete`, `failed`,
    `not_found`, `error`); slower, for diagnosis.
    """
    try:
        return await tactic.list_radar_services(
            active_only=active_only,
            include_docker_status=include_docker_status,
        )
    except TacticError:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to list monitoring services: {e!s}"
        ) from e


@router.get("/evidence", response_model=list[dict[str, Any]])
@shared_limit_fetch
async def get_monitoring_evidence(
    request: Request,
    charger_id: str,
    telemetry_type: str | None = None,
    limit: int = Query(default=2000, ge=1, le=10000),
):
    """Per-observation detector evidence of one entity, newest first.

    Scores, calibrated p-values and the accumulated evidence behind alarms,
    optionally for one telemetry type.
    """
    return await tactic.get_monitoring_evidence(
        charger_id=charger_id,
        telemetry_type=telemetry_type,
        limit=limit,
    )


@router.get("/evidence/chart", response_model=list[dict[str, Any]])
@shared_limit_fetch
async def get_monitoring_chart_evidence(
    request: Request,
    charger_id: str,
    service_id: str | None = Query(default=None, min_length=1, max_length=128),
    after_created: datetime | None = None,
    after_timestamp: datetime | None = None,
    after_service_id: str | None = None,
    after_sequence_number: int | None = Query(default=None, ge=1),
    limit: int = Query(default=2000, ge=1, le=10000),
):
    """Detector evidence of one entity for charts, optionally for one monitor.

    Page with the four `after_*` cursor fields together, taken from the last
    row of the previous page.
    """
    cursor_values = (
        after_created,
        after_timestamp,
        after_service_id,
        after_sequence_number,
    )
    if any(value is not None for value in cursor_values) and not all(
        value is not None for value in cursor_values
    ):
        raise HTTPException(
            status_code=422,
            detail="All monitoring evidence cursor fields are required together",
        )
    if after_created is not None:
        after_created = as_utc(after_created)
    if after_timestamp is not None:
        after_timestamp = as_utc(after_timestamp)
    return await tactic.get_monitoring_chart_evidence(
        charger_id=charger_id,
        service_id=service_id,
        after_created=after_created,
        after_timestamp=after_timestamp,
        after_service_id=after_service_id,
        after_sequence_number=after_sequence_number,
        limit=limit,
    )


@router.post("/start", response_model=ServiceResponse, status_code=202)
@shared_limit_execute
async def start_monitoring_service(
    request: Request,
    config: MonitoringServiceConfig,
):
    """Start a monitor from the form configuration. Administrators only.

    TACTIC runs it as a pipeline. New clients should prefer
    `POST /v1/monitors/pipelines/apply`.
    """
    try:
        return await tactic.start_radar_service(config)
    except TacticError:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to start monitoring service: {e!s}"
        ) from e


@router.get("", response_model=dict[str, Any])
@shared_limit_fetch
async def get_service_details(
    request: Request,
    container_name: str | None = Query(default=None),
    container_id: str | None = Query(default=None),
):
    """One monitor by its container name or container id (exactly one of them)."""
    _require_one_container(container_name, container_id)

    try:
        service_detail = await tactic.get_radar_service_details(
            container_name=container_name,
            container_id=container_id,
        )

        if not service_detail:
            raise HTTPException(status_code=404, detail="Service not found")

        return service_detail
    except (HTTPException, TacticError):
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get service details: {e!s}"
        ) from e


@router.delete("/stop")
@shared_limit_execute
async def stop_monitoring_service(
    request: Request,
    container_name: str | None = Query(default=None),
    container_id: str | None = Query(default=None),
):
    """Stop a monitor's container by name or id. Administrators only."""
    _require_one_container(container_name, container_id)

    try:
        response = await tactic.stop_radar_service(
            container_name=container_name,
            container_id=container_id,
        )

        success = response.get("status") == "stopped"

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Container '{container_name or container_id}'"
                f" not found or could not be stopped",
            )

        return {
            "status": "stopped",
            "message": f"Container '{container_name or container_id}'"
            f" stopped successfully",
        }
    except TacticError:
        raise
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to stop monitoring service: {e!s}"
        ) from e


@router.patch("/{service_id}/label")
@shared_limit_execute
async def rename_monitoring_service(
    request: Request, service_id: str, change: RadarServiceLabel
):
    """Change the name a monitor is shown with. Administrators only."""
    return await tactic.rename_radar_service(service_id, change.display_name)


@router.delete("/{service_id}")
@shared_limit_execute
async def delete_monitoring_service(request: Request, service_id: str):
    """Stop a monitor and delete it, releasing its readings. Administrators only.

    Its alarms stay in Reporting.
    """
    try:
        response = await tactic.delete_radar_service(service_id)

        if response.get("status") != "deleted":
            raise HTTPException(
                status_code=404,
                detail=f"Service '{service_id}' not found or could not be deleted",
            )

        return {
            "status": "deleted",
            "service_id": service_id,
            "message": f"Service '{service_id}' deleted successfully",
        }
    except TacticError:
        raise
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete monitoring service: {e!s}"
        ) from e


@router.get("/models", response_model=dict[str, Any])
@shared_limit_fetch
async def list_detector_models(
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
