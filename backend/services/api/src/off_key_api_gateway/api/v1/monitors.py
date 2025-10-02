from fastapi import APIRouter, HTTPException, Query, Request
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

from ...facades.tactic import tactic
from ..rate_limiter import limiter

router = APIRouter()

shared_limit_fetch = limiter.shared_limit("10/minute", scope="services")
shared_limit_execute = limiter.shared_limit("5/minute", scope="services")


class MonitoringServiceConfig(BaseModel):
    container_name: str = Field(
        ..., description="Name for the monitoring service container"
    )
    service_type: str = Field(
        default="radar", description="Type of monitoring service (radar, custom, etc.)"
    )
    mqtt_topics: List[str] = Field(..., description="List of MQTT topics to monitor")
    model_type: str = Field(
        ..., description="ML model type: isolation_forest, adaptive_svm, knn"
    )
    model_params: Optional[Dict[str, Any]] = Field(
        default=None, description="Model-specific parameters"
    )
    requirements: Optional[List[str]] = Field(
        None, description="List of pip packages to install"
    )
    environment_variables: Optional[Dict[str, str]] = Field(
        None, description="Additional environment variables"
    )


class ServiceResponse(BaseModel):
    service_id: str
    container_id: str
    container_name: str
    status: str
    mqtt_topics: List[str]


@router.get("/all", response_model=List[Dict[str, Any]])
@shared_limit_fetch
async def list_services(
    request: Request,
    active_only: bool = False,
):
    """
    Lists all monitoring services.

    Parameters:
    - active_only: If true, only return active services
    """
    try:
        services = await tactic.list_radar_services(active_only=active_only)
        return services
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to list monitoring services: {str(e)}"
        )


@router.post("/start", response_model=ServiceResponse)
@shared_limit_execute
async def start_monitoring_service(
    request: Request,
    config: MonitoringServiceConfig,
):
    """
    Starts a new monitoring service container via TACTIC orchestration.
    """
    try:
        if config.service_type == "radar":
            response = await tactic.start_radar_service(
                container_name=config.container_name,
                mqtt_topics=config.mqtt_topics,
                model_type=config.model_type,
                model_params=config.model_params,
                mqtt_config=None,
                anomaly_thresholds=None,
                performance_config=None,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported service type: {config.service_type}",
            )

        return response
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to start monitoring service: {str(e)}"
        )


@router.get("", response_model=Dict[str, Any])
@shared_limit_fetch
async def get_service_details(
    request: Request,
    container_name: Optional[str] = Query(default=None),
    container_id: Optional[str] = Query(default=None),
):
    """
    Gets details for a specific monitoring service by container name or ID.
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
        service_detail = await tactic.get_radar_service_details(
            container_name=container_name,
            container_id=container_id,
        )

        if not service_detail:
            raise HTTPException(status_code=404, detail="Service not found")

        return service_detail
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get service details: {str(e)}"
        )


@router.delete("/stop")
@shared_limit_execute
async def stop_monitoring_service(
    request: Request,
    container_name: Optional[str] = Query(default=None),
    container_id: Optional[str] = Query(default=None),
):
    """
    Stops and removes a running monitoring service container via TACTIC.
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
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to stop monitoring service: {str(e)}"
        )
