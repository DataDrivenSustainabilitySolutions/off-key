from fastapi import APIRouter, HTTPException, Depends, Body
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


@router.post("/service/start/", response_model=ServiceResponse)
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


@router.post("/container/stop/{container_name}")
async def stop_monitoring_service(
        container_name: str,
        db: AsyncSession = Depends(get_db_async)
):
    """
    Stops and removes a running Docker container with the specified name.
    Updates the corresponding record in the MonitoringServices database.
    """
    service = MonitoringAsyncService(db)

    success = await service.stop_monitoring_service(container_name)

    if not success:
        raise HTTPException(status_code=404, detail=f"Container '{container_name}' not found or could not be stopped")

    return {"status": "stopped", "message": f"Container '{container_name}' stopped successfully"}


@router.get("/services/", response_model=List[Dict[str, Any]])
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


@router.get("/service/{container_name}", response_model=Dict[str, Any])
async def get_service_details(
        container_name: str,
        db: AsyncSession = Depends(get_db_async)
):
    """
    Gets details for a specific monitoring service.
    """
    service = MonitoringAsyncService(db)
    service_details = await service.get_monitoring_service(container_name)

    if not service_details:
        raise HTTPException(status_code=404, detail=f"Service with container name '{container_name}' not found")

    return service_details

# Old API
# @router.post("/services/")
# def create_service_sync(
#         mqtt_topic: str,
#         container_name: Optional[str] = None,
#         db: AsyncSession = Depends(get_db_async)
# ):
#     """
#     Backward compatibility - creates a service synchronously
#     """
#     if not container_name:
#         import uuid
#         container_name = f"ml_service_{str(uuid.uuid4())}"
#
#     try:
#         service = create_monitoring_container(
#             container_name=container_name,
#             mqtt_topics=[mqtt_topic],
#             db_url=str(db.bind.url)
#         )
#
#         return {
#             "service_id": service.id,
#             "container_id": service.container_id,
#             "container_name": container_name
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))