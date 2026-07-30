import uuid
from datetime import datetime
from typing import Any

from off_key_core.config.logs import logger
from off_key_core.db.models import MonitoringService, MqttTopic
from off_key_core.schemas.radar import RadarOperationalStatus
from off_key_core.utils.mqtt_topics import (
    mqtt_topic_filters_overlap,
    normalize_static_monitoring_topics,
    normalize_telemetry_topic_filters,
)
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.registry import ModelRegistryService
from ..radar_status import (
    TERMINAL_WORKLOAD_STATES,
    apply_terminal_operational_status,
    derive_operational_status,
)
from .radar_environment import (
    build_radar_config_fingerprint,
    build_radar_environment,
)
from .radar_workloads import RadarWorkloadManager, get_async_docker


class RadarOrchestrationService:
    """
    Service responsible for orchestrating RADAR
    (MQTT Real-Time Anomaly Detector) containers.

    This service handles:
    - Creating RADAR containers with specific model and parameters
    - Managing RADAR service lifecycle (start, stop, status)
    - Parsing and applying environment variables from RADAR configuration
    """

    def __init__(self, session: AsyncSession, model_registry: ModelRegistryService):
        self.session: AsyncSession = session
        self.workloads = RadarWorkloadManager(get_async_docker())
        self.model_registry = model_registry
        logger.info("RadarOrchestrationService initialized.")

    async def create_radar_service(
        self,
        container_name: str,
        mqtt_topics: list[str],
        strategy: str = "static_baseline",
        model_type: str = "pyod_iforest",
        model_params: dict[str, Any] | None = None,
        mqtt_config: dict[str, Any] | None = None,
        performance_config: dict[str, Any] | None = None,
        static_baseline_config: dict[str, Any] | None = None,
    ) -> MonitoringService:
        """
        Create and start a RADAR Docker service for anomaly detection.

        Args:
            container_name (str): Name for the Docker container
            mqtt_topics (List[str]): List of MQTT topics to monitor
            strategy (str): Monitoring strategy selected by the user
            model_type (str): Static PyOD model type
            model_params (Dict, optional): Model-specific parameters
            mqtt_config (Dict, optional): MQTT connection configuration
            performance_config (Dict, optional): Performance and resource settings
            static_baseline_config (Dict, optional): Static conformal settings

        Returns:
            MonitoringService: The created monitoring service database entry
        """
        mqtt_topics = normalize_static_monitoring_topics(mqtt_topics)
        strategy = (strategy or "static_baseline").strip().lower()
        await self._assert_topics_available(
            mqtt_topics=mqtt_topics,
            container_name=container_name,
        )
        db_service_id = str(uuid.uuid4())
        env_vars = build_radar_environment(
            service_id=db_service_id,
            mqtt_topics=mqtt_topics,
            strategy=strategy,
            model_type=model_type,
            model_params=model_params or {},
            mqtt_config=mqtt_config or {},
            performance_config=performance_config or {},
            static_baseline_config=static_baseline_config or {},
            model_registry=self.model_registry,
        )
        config_fingerprint = build_radar_config_fingerprint(env_vars)

        # Check if service with this name already exists
        query = select(MonitoringService).where(
            MonitoringService.container_name == container_name
        )
        result = await self.session.execute(query)
        existing_service = result.scalars().first()

        if existing_service:
            resolved_service = await self._resolve_existing_service_request(
                existing_service=existing_service,
                container_name=container_name,
                mqtt_topics=mqtt_topics,
                strategy=strategy,
                model_type=env_vars.get("RADAR_MODEL_TYPE", ""),
                config_fingerprint=config_fingerprint,
            )
            if resolved_service:
                return resolved_service

        # Create the RADAR workload (Swarm service when available, otherwise container)
        docker_workload: Any = None
        try:
            docker_workload = await self.workloads.create(db_service_id, env_vars)
            await self.workloads.validate_started(docker_workload)

            # Create monitoring service record
            service_record = MonitoringService(
                id=db_service_id,
                container_id=docker_workload.id,
                container_name=container_name,
                mqtt_topic=mqtt_topics,
                created_at=datetime.now(),
                status=True,
                operational_stage="starting",
                operational_status=RadarOperationalStatus(stage="starting").model_dump(
                    mode="json", exclude_none=True
                ),
                operational_updated_at=None,
            )

            # Add to database
            self.session.add(service_record)
            await self.session.commit()

            logger.info(f"RADAR workload created with ID: {docker_workload.id}")
            logger.info(f"RADAR service added to database with ID: {service_record.id}")

            return service_record

        except Exception as e:
            await self.session.rollback()
            if docker_workload is not None:
                await self.workloads.remove_after_failure(docker_workload)
            logger.error(f"Failed to create RADAR service: {e}")
            raise

    async def _assert_topics_available(
        self, *, mqtt_topics: list[str], container_name: str
    ) -> None:
        """Serialize claims and reject overlap with another active service."""
        bind = getattr(self.session, "bind", None)
        dialect_name = getattr(getattr(bind, "dialect", None), "name", None)
        if dialect_name == "postgresql":
            await self.session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtext('off-key-radar-sensor-assignments'))"
                )
            )

        active_services = await self._reconcile_active_topic_claims()
        for active_service in active_services:
            if active_service.container_name == container_name:
                continue
            active_topics = active_service.mqtt_topic or []
            for requested_topic in mqtt_topics:
                for active_topic in active_topics:
                    if mqtt_topic_filters_overlap(requested_topic, str(active_topic)):
                        raise ValueError(
                            f"MQTT topic '{requested_topic}' overlaps active service "
                            f"'{active_service.container_name}' topic "
                            f"'{active_topic}'. A sensor stream can belong to only "
                            "one monitoring service."
                        )

    async def _reconcile_active_topic_claims(self) -> list[MonitoringService]:
        result = await self.session.execute(
            select(MonitoringService).where(MonitoringService.status.is_(True))
        )
        claimants: list[MonitoringService] = []
        reconciled = False
        for service in result.scalars().all():
            docker_status, _ = await self.workloads.get_status_and_labels(
                getattr(service, "container_id", "") or ""
            )
            if docker_status in TERMINAL_WORKLOAD_STATES:
                service.status = False
                apply_terminal_operational_status(service, docker_status)
                reconciled = True
                continue
            claimants.append(service)

        if reconciled:
            await self.session.flush()
        return claimants

    async def _resolve_existing_service_request(
        self,
        *,
        existing_service: MonitoringService,
        container_name: str,
        mqtt_topics: list[str],
        strategy: str,
        model_type: str,
        config_fingerprint: str,
    ) -> MonitoringService | None:
        """Reuse a matching live workload or clear a stale row before recreation."""
        docker_status, labels = await self.workloads.get_status_and_labels(
            existing_service.container_id or ""
        )
        if docker_status == "error":
            raise ValueError(
                f"RADAR service name '{container_name}' already exists, but "
                "Docker status could not be verified. Try again after Docker "
                "connectivity recovers."
            )

        if docker_status != "running":
            existing_service.status = False
            apply_terminal_operational_status(existing_service, docker_status)
            await self._delete_service_rows_by_ids([existing_service.id])
            await self.session.commit()
            logger.info(
                "Deleted stale RADAR service row %s before recreating %s "
                "(docker_status=%s)",
                existing_service.id,
                container_name,
                docker_status,
            )
            return None

        if not existing_service.status:
            existing_service.status = True

        existing_topics = normalize_telemetry_topic_filters(existing_service.mqtt_topic)
        if existing_topics != mqtt_topics:
            raise ValueError(
                f"RADAR service name '{container_name}' already belongs to a "
                "running service with different MQTT topics."
            )

        existing_fingerprint = labels.get("radar_config_fingerprint")
        if existing_fingerprint and existing_fingerprint != config_fingerprint:
            raise ValueError(
                f"RADAR service name '{container_name}' already belongs to a "
                "running service with a different RADAR configuration."
            )

        expected_labels = {
            "monitoring_strategy": strategy,
            "radar_model_type": (model_type or "").strip().lower(),
        }
        for label_key, expected_value in expected_labels.items():
            label_value = labels.get(label_key)
            if label_value and label_value.strip().lower() != expected_value:
                raise ValueError(
                    f"RADAR service name '{container_name}' already belongs to a "
                    f"running service with a different {label_key}."
                )

        logger.info(
            "RADAR service %s already exists with matching active workload",
            container_name,
        )
        return existing_service

    async def teardown_managed_radar_workloads(self) -> dict[str, int]:
        """
        Remove all TACTIC-managed RADAR Docker workloads and clear service records.

        Returns:
            Dict[str, int]: Cleanup summary counters.
        """
        managed_workload_ids = await self.workloads.list_managed_ids()
        target_ids = set(managed_workload_ids)

        removed_workloads = 0
        successfully_removed: set[str] = set()
        removal_failures: list[str] = []

        for workload_id in target_ids:
            try:
                removed = await self.workloads.remove(workload_id)
                if removed:
                    removed_workloads += 1
                successfully_removed.add(workload_id)
            except Exception as exc:
                removal_failures.append(f"{workload_id}: {exc}")

        db_rows_deleted = 0
        if successfully_removed:
            service_id_result = await self.session.execute(
                select(MonitoringService.id).where(
                    MonitoringService.container_id.in_(successfully_removed)
                )
            )
            service_ids = list(service_id_result.scalars().all())
            db_rows_deleted = await self._delete_service_rows_by_ids(service_ids)
            await self.session.commit()

        if removal_failures:
            failures = "; ".join(removal_failures)
            raise RuntimeError(
                f"Failed to remove one or more managed RADAR workloads: {failures}"
            )

        return {
            "db_rows_deleted": db_rows_deleted,
            "docker_workloads_removed": removed_workloads,
            "workloads_targeted": len(target_ids),
        }

    async def _delete_service_rows_by_ids(self, service_ids: list[str]) -> int:
        if not service_ids:
            return 0

        await self.session.execute(
            delete(MqttTopic).where(MqttTopic.service_id.in_(service_ids))
        )
        delete_result = await self.session.execute(
            delete(MonitoringService).where(MonitoringService.id.in_(service_ids))
        )
        return int(delete_result.rowcount or 0)

    async def _delete_service(self, service: MonitoringService) -> bool:
        try:
            removed_workload = await self.workloads.remove(service.container_id)
            deleted_rows = await self._delete_service_rows_by_ids([service.id])
            await self.session.commit()
            logger.info(
                "Deleted RADAR service %s (workload_removed=%s)",
                service.id,
                removed_workload,
            )
            return deleted_rows > 0
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to delete RADAR service %s: %s", service.id, e)
            return False

    async def delete_radar_service(self, service_id: str) -> bool:
        stmt = select(MonitoringService).where(MonitoringService.id == service_id)
        result = await self.session.execute(stmt)
        service = result.scalars().first()

        if not service:
            logger.warning("No RADAR service found with id: %s", service_id)
            return False

        return await self._delete_service(service)

    async def stop_radar_service(
        self, container_name: str | None = None, container_id: str | None = None
    ) -> bool:
        """
        Stop and remove a running RADAR service.

        Args:
            container_name (str): Name of the container to stop
            container_id (str): ID of the container to stop

        Returns:
            bool: True if service was stopped, False otherwise
        """
        if (not container_name and not container_id) or (
            container_name and container_id
        ):
            logger.warning(
                "Invalid stop request: provide exactly one identifier "
                "(container_name or container_id)"
            )
            return False

        # Find the service in the database
        stmt = select(MonitoringService)
        lookup_target = container_name or container_id

        if container_name:
            stmt = stmt.where(MonitoringService.container_name == container_name)
        elif container_id:
            stmt = stmt.where(MonitoringService.container_id == container_id)

        result = await self.session.execute(stmt)
        service = result.scalars().first()

        if not service:
            logger.warning(
                "No RADAR service found with identifier: %s",
                lookup_target,
            )
            return False

        return await self._delete_service(service)

    async def list_radar_services(
        self, active_only: bool = False, include_docker_status: bool = False
    ) -> list[dict[str, Any]]:
        """
        List all RADAR services.

        Args:
            active_only (bool): If True, only return active services
            include_docker_status (bool): If True, check actual Docker container
                status for each service (slower but more accurate)

        Returns:
            List[Dict]: List of RADAR services with their details
        """
        query = select(MonitoringService)
        if active_only:
            query = query.where(MonitoringService.status.is_(True))

        result = await self.session.execute(query)
        services = result.scalars().all()

        service_list = []
        for service in services:
            service_dict = {
                "id": service.id,
                "container_id": service.container_id,
                "container_name": service.container_name,
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

            service_list.append(service_dict)

        return service_list

    async def get_radar_service(
        self, container_name: str | None = None, container_id: str | None = None
    ) -> dict[str, Any] | None:
        """
        Get details for a specific RADAR service.

        Args:
            container_name (str): Name of the container
            container_id (str): ID of the container

        Returns:
            Optional[Dict]: Service details or None if not found
        """
        if (not container_name and not container_id) or (
            container_name and container_id
        ):
            logger.warning(
                "Invalid get request: provide exactly one identifier "
                "(container_name or container_id)"
            )
            return None

        stmt = select(MonitoringService)

        if container_name:
            stmt = stmt.where(MonitoringService.container_name == container_name)
        elif container_id:
            stmt = stmt.where(MonitoringService.container_id == container_id)

        result = await self.session.execute(stmt)
        service = result.scalars().first()

        if not service:
            return None

        # Check actual workload status in Docker
        docker_service_status, labels = await self.workloads.get_status_and_labels(
            service.container_id
        )

        return {
            "id": service.id,
            "container_id": service.container_id,
            "container_name": service.container_name,
            "mqtt_topics": service.mqtt_topic,
            "db_status": service.status,
            "docker_status": docker_service_status,
            "operational_status": derive_operational_status(
                service, docker_service_status
            ),
            "monitoring_strategy": labels.get("monitoring_strategy"),
            "model_type": labels.get("radar_model_type"),
            "created_at": (
                service.created_at.isoformat() if service.created_at else None
            ),
        }
