from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

from ...db.base import get_db_async
from ...services.services import MonitoringAsyncService

router = APIRouter()


class ContainerConfig(BaseModel):
    container_name: str = Field(..., description="Name for the Docker container")
    mqtt_topics: List[str] = Field(..., description="List of MQTT topics to monitor")
    requirements: Optional[List[str]] = Field(None, description="List of pip packages to install")
    environment_variables: Optional[Dict[str, str]] = Field(None, description="Additional environment variables")


class ServiceResponse(BaseModel):
    service_id: str
    container_id: str
    container_name: str
    status: str
    mqtt_topics: List[str]


@router.get("/all/", response_model=List[Dict[str, Any]])
async def list_services(
        active_only: bool = False,
        db: AsyncSession = Depends(get_db_async)
):
    """
    Lists all monitoring services.

    Parameters:
    - active_only: If true, only return active services
    """
    service = MonitoringAsyncService(db)
    services = await service.list_monitoring_services(active_only)
    return services


@router.post("/start/", response_model=ServiceResponse)
async def start_monitoring_service(
        config: ContainerConfig,
        db: AsyncSession = Depends(get_db_async)
):
    """
    Starts a new Docker container running a monitoring service for the given MQTT topics.
    Configuration details are stored in the MonitoringServices database.
    """
    service = MonitoringAsyncService(db)

    try:
        monitoring_service = await service.create_monitoring_service(
            container_name=config.container_name,
            mqtt_topics=config.mqtt_topics,
            requirements=config.requirements,
            environment_variables=config.environment_variables
        )

        return {
            "service_id": monitoring_service.id,
            "container_id": monitoring_service.container_id,
            "container_name": monitoring_service.container_name,
            "status": "running" if monitoring_service.status else "stopped",
            "mqtt_topics": monitoring_service.mqtt_topic
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start monitoring service: {str(e)}")


@router.get("/", response_model=Dict[str, Any])
async def get_service_details(
        container_name: Optional[str] = Query(default=None),
        container_id: Optional[str] = Query(default=None),
        db: AsyncSession = Depends(get_db_async)
):
    """
    Gets details for a specific monitoring service by container name or ID.
    """
    if not container_name and not container_id:
        raise HTTPException(status_code=400, detail="You must provide either container_name or container_id.")

    if container_name and container_id:
        raise HTTPException(status_code=400, detail="Provide only one of container_name or container_id.")

    service = MonitoringAsyncService(db)
    service_details = await service.get_monitoring_service(container_name, container_id)

    if not service_details:
        raise HTTPException(status_code=404, detail=f"Service not found")

    return service_details


@router.delete("/stop/")
async def stop_monitoring_service(
        container_name: Optional[str] = Query(default=None),
        container_id: Optional[str] = Query(default=None),
        db: AsyncSession = Depends(get_db_async)
):
    """
    Stops and removes a running Docker container with the specified name.
    Updates the corresponding record in the MonitoringServices database.
    """
    if not container_name and not container_id:
        raise HTTPException(status_code=400, detail="You must provide either container_name or container_id.")

    if container_name and container_id:
        raise HTTPException(status_code=400, detail="Provide only one of container_name or container_id.")

    service = MonitoringAsyncService(db)

    success = await service.stop_monitoring_service(container_name, container_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Container '{container_name}' not found or could not be stopped")

    return {"status": "stopped", "message": f"Container '{container_name}' stopped and deleted successfully"}
