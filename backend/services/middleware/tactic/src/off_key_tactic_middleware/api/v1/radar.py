from fastapi import APIRouter, Depends, HTTPException, Query, Request
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from off_key_core.utils.mqtt_topics import normalize_static_monitoring_topics

from off_key_core.schemas.radar import (
    MonitoringStrategy,
    PerformanceConfig,
    StaticBaselineConfig,
)
from ...models.registry import ModelRegistryService
from ...services.orchestration.radar import (
    RadarOrchestrationService,
)
from ...provider import (
    get_model_registry_service,
    get_radar_orchestration_service,
)

router = APIRouter()


class RadarConfig(BaseModel):
    """Configuration for creating a RADAR anomaly detection service."""

    model_config = ConfigDict(extra="forbid")

    container_name: str = Field(..., description="Name for the Docker container")
    mqtt_topics: List[str] = Field(..., description="List of MQTT topics to monitor")

    # Model Configuration
    strategy: MonitoringStrategy = Field(
        default="static_baseline",
        description="Static baseline monitoring strategy.",
    )
    model_type: str = Field(
        default="pyod_iforest",
        description="ML model type. Use GET /api/v1/models/ to see available models.",
    )
    model_params: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Model-specific hyperparameters. Use GET /api/v1/models/ to see"
        " available parameters for each model.",
    )
    # MQTT Configuration
    mqtt_config: Optional[Dict[str, Any]] = Field(
        default=None, description="MQTT connection settings"
    )

    # Performance Configuration
    performance_config: Optional[PerformanceConfig] = Field(
        default=None, description="Performance and resource settings"
    )
    static_baseline_config: Optional[StaticBaselineConfig] = Field(
        default=None,
        description="Static baseline conformal detector settings.",
    )

    @field_validator("mqtt_topics")
    @classmethod
    def validate_mqtt_topics(cls, value: List[str]) -> List[str]:
        return normalize_static_monitoring_topics(value)


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
            strategy=config.strategy,
            model_type=config.model_type,
            model_params=config.model_params,
            mqtt_config=config.mqtt_config,
            performance_config=(
                config.performance_config.model_dump(exclude_none=True)
                if config.performance_config
                else None
            ),
            static_baseline_config=(
                config.static_baseline_config.model_dump(exclude_none=True)
                if config.static_baseline_config
                else None
            ),
        )

        return {
            "service_id": radar_service.id,
            "container_id": radar_service.container_id,
            "container_name": radar_service.container_name,
            "status": "running" if radar_service.status else "stopped",
            "mqtt_topics": radar_service.mqtt_topic,
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to stop RADAR service: {str(e)}"
        )


@router.delete("/radar/services/{service_id}")
async def delete_radar_service(
    request: Request,
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete RADAR service: {str(e)}"
        )


@router.get("/radar/models/", response_model=List[Dict[str, Any]])
async def list_available_models(
    request: Request,
    model_registry: ModelRegistryService = Depends(get_model_registry_service),
):
    """
    Lists all available anomaly detection models and their hyperparameters.

    Returns information about each model including:
    - family: Model family (forest, distance, svm, etc.)
    - description: What the model does
    - complexity: Computational complexity
    - memory_usage: Expected memory footprint
    - parameter_schema: JSON schema for hyperparameters
    - default_parameters: Default parameter values

    Use this endpoint to discover available models and their configuration options
    before starting a RADAR service.
    """
    try:
        return model_registry.get_available_models()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get available models: {str(e)}"
        )
