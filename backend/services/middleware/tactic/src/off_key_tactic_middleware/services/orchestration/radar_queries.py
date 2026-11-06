"""Read projections of monitoring services for the TACTIC API."""

import asyncio
from typing import Any

from off_key_core.db.collection_runtime import read_collection_runtime
from off_key_core.db.models import MonitoringService
from off_key_core.schemas.system_collection import SystemCollectionDefinition
from sqlalchemy import select

from .radar_status import derive_operational_status


async def find_service(session, service_id: str):
    result = await session.execute(
        select(MonitoringService).where(MonitoringService.id == service_id)
    )
    return result.scalars().first()


def service_summary(
    service: MonitoringService,
    catalogue: SystemCollectionDefinition,
    probe: tuple[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    configuration = service.launch_config or {}
    monitoring = configuration.get("monitoring") or {}
    docker_status, labels = probe if probe is not None else (None, {})
    operational_status = derive_operational_status(service, docker_status)
    # Large graph snapshots are returned only for the selected service.
    operational_status.pop("pipeline_state", None)
    summary = {
        "id": service.id,
        "container_id": service.container_id,
        "container_name": service.container_name,
        "display_name": configuration.get("display_name"),
        "monitoring_strategy": (
            labels.get("monitoring_strategy") if labels else monitoring.get("strategy")
        ),
        "model_type": (
            labels.get("radar_model_type") if labels else monitoring.get("model_type")
        ),
        "mqtt_topics": service.mqtt_topic,
        # Catalogue readings the monitor watches, so callers need no MQTT rules.
        "stream_ids": catalogue.watched_by(service.mqtt_topic),
        "status": service.status,
        "operational_status": operational_status,
        "created_at": service.created_at.isoformat() if service.created_at else None,
    }
    if probe is not None:
        summary["docker_status"] = docker_status
    return summary


class RadarServiceQueries:
    def __init__(self, session, workloads):
        self.session = session
        self.workloads = workloads

    async def list(
        self, *, active_only: bool = False, include_docker_status: bool = False
    ) -> list[dict[str, Any]]:
        """List services; Docker labels override saved strategy when probed."""
        query = select(MonitoringService)
        if active_only:
            query = query.where(MonitoringService.status.is_(True))

        result = await self.session.execute(query)
        services = result.scalars().all()
        catalogue = (await read_collection_runtime(self.session)).catalog

        if not include_docker_status:
            return [service_summary(service, catalogue) for service in services]

        # AsyncDocker already bounds concurrent requests across callers.
        probes = await asyncio.gather(
            *(
                self.workloads.get_status_and_labels(item.container_id)
                for item in services
            )
        )
        return [
            service_summary(service, catalogue, probe)
            for service, probe in zip(services, probes, strict=True)
        ]

    async def get(self, service_id: str) -> dict[str, Any] | None:
        """One service; saved configuration wins over Docker labels."""
        service = await find_service(self.session, service_id)
        if not service:
            return None
        catalogue = (await read_collection_runtime(self.session)).catalog

        # Check actual workload status in Docker
        docker_service_status, labels = await self.workloads.get_status_and_labels(
            service.container_id
        )

        configuration = getattr(service, "launch_config", None) or {}
        monitoring = configuration.get("monitoring") or {}

        return {
            "id": service.id,
            "container_id": service.container_id,
            "container_name": service.container_name,
            "display_name": configuration.get("display_name"),
            "configuration": {
                "monitoring": monitoring,
                "performance_config": configuration.get("performance_config") or {},
            },
            "mqtt_topics": service.mqtt_topic,
            "stream_ids": catalogue.watched_by(service.mqtt_topic),
            "status": service.status,
            "docker_status": docker_service_status,
            "operational_status": derive_operational_status(
                service, docker_service_status
            ),
            "monitoring_strategy": monitoring.get("strategy")
            or labels.get("monitoring_strategy"),
            "model_type": monitoring.get("model_type")
            or labels.get("radar_model_type"),
            "created_at": (
                service.created_at.isoformat() if service.created_at else None
            ),
        }
