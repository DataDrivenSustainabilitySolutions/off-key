"""Read projections of monitoring services for the TACTIC API."""

from typing import Any

from off_key_core.config.logs import logger
from off_key_core.db.models import MonitoringService
from sqlalchemy import select

from .radar_status import derive_operational_status


def exactly_one(container_name, container_id, purpose: str) -> bool:
    """Require exactly one workload identifier, logging a rejected request."""
    if bool(container_name) == bool(container_id):
        logger.warning(
            "Invalid %s request: provide exactly one identifier "
            "(container_name or container_id)",
            purpose,
        )
        return False
    return True


async def find_service(session, container_name, container_id):
    stmt = select(MonitoringService)
    if container_name:
        stmt = stmt.where(MonitoringService.container_name == container_name)
    else:
        stmt = stmt.where(MonitoringService.container_id == container_id)
    result = await session.execute(stmt)
    return result.scalars().first()


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

        service_list = []
        for service in services:
            configuration = getattr(service, "launch_config", None) or {}
            monitoring = configuration.get("monitoring") or {}
            service_dict = {
                "id": service.id,
                "container_id": service.container_id,
                "container_name": service.container_name,
                "display_name": configuration.get("display_name"),
                "monitoring_strategy": monitoring.get("strategy"),
                "model_type": monitoring.get("model_type"),
                "mqtt_topics": service.mqtt_topic,
                "status": service.status,
                "operational_status": derive_operational_status(service),
                "created_at": (
                    service.created_at.isoformat() if service.created_at else None
                ),
            }
            # Optionally check actual Docker state
            if include_docker_status:
                docker_status, labels = await self.workloads.get_status_and_labels(
                    service.container_id
                )
                service_dict["docker_status"] = docker_status
                service_dict["operational_status"] = derive_operational_status(
                    service, docker_status
                )
                if labels:
                    service_dict["monitoring_strategy"] = labels.get(
                        "monitoring_strategy"
                    )
                    service_dict["model_type"] = labels.get("radar_model_type")

            # Large graph snapshots are returned only for the selected service.
            service_dict["operational_status"].pop("pipeline_state", None)
            service_list.append(service_dict)

        return service_list

    async def get(
        self, *, container_name: str | None = None, container_id: str | None = None
    ) -> dict[str, Any] | None:
        """One service; saved configuration wins over Docker labels."""
        if not exactly_one(container_name, container_id, "get"):
            return None

        service = await find_service(self.session, container_name, container_id)
        if not service:
            return None

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
            "db_status": service.status,
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
