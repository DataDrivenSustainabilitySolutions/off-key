from fastapi import APIRouter, HTTPException, Depends, Query, Request
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

from off_key_middleware_tactic.services.orchestration.radar import (
    RadarOrchestrationService,
)
from ...provider import get_radar_orchestration_service

router = APIRouter()


class RadarConfig(BaseModel):
    """Configuration for creating a RADAR anomaly detection service."""

    container_name: str = Field(..., description="Name for the Docker container")
    mqtt_topics: List[str] = Field(..., description="List of MQTT topics to monitor")

    # Model Configuration
    model_type: str = Field(
        default="isolation_forest",
        description="ML model type: isolation_forest, adaptive_svm, knn",
    )
    model_params: Optional[Dict[str, Any]] = Field(
        default=None, description="Model-specific parameters"
    )

    # MQTT Configuration
    mqtt_config: Optional[Dict[str, Any]] = Field(
        default=None, description="MQTT connection settings"
    )

    # Anomaly Detection Configuration
    anomaly_thresholds: Optional[Dict[str, float]] = Field(
        default=None,
        description="Anomaly detection thresholds (medium, high, critical)",
    )

    # Performance Configuration
    performance_config: Optional[Dict[str, Any]] = Field(
        default=None, description="Performance and resource settings"
    )


class RadarServiceResponse(BaseModel):
    """Response model for RADAR service operations."""

    service_id: str
    container_id: str
    container_name: str
    status: str
    mqtt_topics: List[str]


@router.get("/radar/services/", response_model=List[Dict[str, Any]])
async def list_radar_services(
    request: Request,
    active_only: bool = False,
    service: RadarOrchestrationService = Depends(get_radar_orchestration_service),
):
    """
    Lists all RADAR anomaly detection services.

    Parameters:
    - active_only: If true, only return active services
    """
    try:
        services = await service.list_radar_services(active_only)
        return services
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to list RADAR services: {str(e)}"
        )


@router.post("/radar/services/start/", response_model=RadarServiceResponse)
async def start_radar_service(
    request: Request,
    config: RadarConfig,
    service: RadarOrchestrationService = Depends(get_radar_orchestration_service),
):
    """
    Starts a new RADAR Docker service for anomaly detection on specified MQTT topics.

    The RADAR service will:
    - Subscribe to the specified MQTT topics
    - Apply the configured ML model for anomaly detection
    - Use the provided thresholds and performance settings
    - Store results in the database
    """
    try:
        radar_service = await service.create_radar_service(
            container_name=config.container_name,
            mqtt_topics=config.mqtt_topics,
            model_type=config.model_type,
            model_params=config.model_params,
            mqtt_config=config.mqtt_config,
            anomaly_thresholds=config.anomaly_thresholds,
            performance_config=config.performance_config,
        )

        return {
            "service_id": radar_service.id,
            "container_id": radar_service.container_id,
            "container_name": radar_service.container_name,
            "status": "running" if radar_service.status else "stopped",
            "mqtt_topics": radar_service.mqtt_topic,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to start RADAR service: {str(e)}"
        )


@router.get("/radar/services/details/", response_model=Dict[str, Any])
async def get_radar_service_details(
    request: Request,
    container_name: Optional[str] = Query(default=None),
    container_id: Optional[str] = Query(default=None),
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get RADAR service details: {str(e)}"
        )


@router.delete("/radar/services/stop/")
async def stop_radar_service(
    request: Request,
    container_name: Optional[str] = Query(default=None),
    container_id: Optional[str] = Query(default=None),
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
        success = await service.stop_radar_service(container_name, container_id)

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"RADAR service '{container_name}'"
                f" not found or could not be stopped",
            )

        return {
            "status": "stopped",
            "message": f"RADAR service '{container_name}'"
            f" stopped and deleted successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to stop RADAR service: {str(e)}"
        )
