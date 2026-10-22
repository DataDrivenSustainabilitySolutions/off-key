from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from off_key_core.db.maintenance import DeploymentInProgressError
from off_key_core.schemas.radar import RadarServiceLabel
from off_key_core.schemas.radar import RadarStartConfig as RadarConfig
from pydantic import BaseModel

from ...domain import DomainError
from ...provider import get_form_monitor_starter, get_radar_orchestration_service
from ...services.orchestration.radar import (
    RadarOrchestrationService,
)
from ..errors import http_error

router = APIRouter()


class RadarServiceResponse(BaseModel):
    """A form monitor accepted as a pipeline activation; its workload starts next."""

    service_id: str
    activation_id: str
    container_name: str
    status: str
    mqtt_topics: list[str]


@router.get("/radar/services/", response_model=list[dict[str, Any]])
async def list_radar_services(
    active_only: bool = False,
    include_docker_status: bool = False,
    service: RadarOrchestrationService = Depends(get_radar_orchestration_service),
):
    """
    Lists all RADAR anomaly detection services.

    Parameters:
    - active_only: If true, only return active services
    - include_docker_status: If true, check actual Docker container status
      for each service. This is slower but provides accurate real-time status.
    """
    try:
        return await service.list_radar_services(active_only, include_docker_status)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to list RADAR services: {e!s}"
        ) from e


@router.post(
    "/radar/services/start/",
    response_model=RadarServiceResponse,
    status_code=202,
)
async def start_radar_service(
    config: RadarConfig, start_form_monitor=Depends(get_form_monitor_starter)
):
    """Start a monitor configured with a setup form as an equivalent pipeline."""
    try:
        activation = await start_form_monitor(config)
    except DomainError as exc:
        raise http_error(exc) from exc
    return {
        "service_id": activation.service_id,
        "activation_id": activation.id,
        "container_name": f"pipeline-{activation.service_id}",
        "status": activation.phase,
        "mqtt_topics": config.mqtt_topics,
    }


@router.get("/radar/services/details/", response_model=dict[str, Any])
async def get_radar_service_details(
    container_name: str | None = Query(default=None),
    container_id: str | None = Query(default=None),
    service: RadarOrchestrationService = Depends(get_radar_orchestration_service),
):
    """
    Gets details for a specific RADAR service by container name or ID.
    """
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

    try:
        service_detail = await service.get_radar_service(container_name, container_id)

        if not service_detail:
            raise HTTPException(status_code=404, detail="RADAR service not found")

        return service_detail
    except (HTTPException, DeploymentInProgressError):
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get RADAR service details: {e!s}"
        ) from e


@router.delete("/radar/services/stop/")
async def stop_radar_service(
    container_name: str | None = Query(default=None),
    container_id: str | None = Query(default=None),
    service: RadarOrchestrationService = Depends(get_radar_orchestration_service),
):
    """
    Stops and removes a running RADAR Docker service.
    Updates the corresponding record in the database.
    """
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

    try:
        lookup_target = container_name if container_name else container_id
        success = await service.stop_radar_service(container_name, container_id)

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"RADAR service '{lookup_target}'"
                f" not found or could not be stopped",
            )

        return {
            "status": "stopped",
            "message": f"RADAR service '{lookup_target}'"
            f" stopped and deleted successfully",
        }
    except (HTTPException, DeploymentInProgressError):
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to stop RADAR service: {e!s}"
        ) from e


@router.patch("/radar/services/{service_id}/label")
async def rename_radar_service(
    service_id: str,
    change: RadarServiceLabel,
    service: RadarOrchestrationService = Depends(get_radar_orchestration_service),
):
    if not await service.rename_radar_service(service_id, change.display_name):
        raise HTTPException(status_code=404, detail="Monitoring service not found")
    return {"id": service_id, "display_name": change.display_name}


@router.delete("/radar/services/{service_id}")
async def delete_radar_service(
    service_id: str,
    service: RadarOrchestrationService = Depends(get_radar_orchestration_service),
):
    """
    Stops any backing RADAR workload and deletes the service record.
    """
    try:
        success = await service.delete_radar_service(service_id)

        if not success:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"RADAR service '{service_id}' not found or could not be deleted"
                ),
            )

        return {
            "status": "deleted",
            "service_id": service_id,
            "message": f"RADAR service '{service_id}' deleted successfully",
        }
    except (HTTPException, DeploymentInProgressError):
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete RADAR service: {e!s}"
        ) from e
