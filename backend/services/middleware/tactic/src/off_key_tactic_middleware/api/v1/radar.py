from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from off_key_core.db.maintenance import DeploymentInProgressError
from off_key_core.schemas.radar import MonitorSetup, RadarServiceLabel
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
    reading_ids: list[str]


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
    setup: MonitorSetup, start_form_monitor=Depends(get_form_monitor_starter)
):
    """Start a monitor set up with the forms as an equivalent pipeline."""
    try:
        activation = await start_form_monitor(setup)
    except DomainError as exc:
        raise http_error(exc) from exc
    return {
        "service_id": activation.service_id,
        "activation_id": activation.id,
        "container_name": f"pipeline-{activation.service_id}",
        "status": activation.phase,
        "reading_ids": setup.reading_ids,
    }


@router.get("/radar/services/{service_id}", response_model=dict[str, Any])
async def get_radar_service_details(
    service_id: str,
    service: RadarOrchestrationService = Depends(get_radar_orchestration_service),
):
    """One RADAR service by its id."""
    try:
        service_detail = await service.get_radar_service(service_id)

        if not service_detail:
            raise HTTPException(status_code=404, detail="RADAR service not found")

        return service_detail
    except (HTTPException, DeploymentInProgressError):
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get RADAR service details: {e!s}"
        ) from e


@router.post("/radar/services/{service_id}/stop")
async def stop_radar_service(
    service_id: str,
    service: RadarOrchestrationService = Depends(get_radar_orchestration_service),
):
    """Stop a RADAR service and remove its workload; the record is retired."""
    try:
        success = await service.stop_radar_service(service_id)

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"RADAR service '{service_id}' was not found or not stopped",
            )

        return {"status": "stopped", "service_id": service_id}
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
