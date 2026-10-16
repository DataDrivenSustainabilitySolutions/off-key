import json
import uuid
from datetime import UTC, datetime
from typing import Any

from off_key_core.config.logs import logger
from off_key_core.db.collection import (
    lock_collection_configuration,
)
from off_key_core.db.collection_runtime import monitoring_collection_fingerprint
from off_key_core.db.maintenance import require_application_writes
from off_key_core.db.models import MonitoringService, MqttTopic
from off_key_core.db.pipeline_claims import monitor_claim_condition, pending_activations
from off_key_core.db.pipeline_locks import lock_execution_records
from off_key_core.schemas.radar import (
    RadarOperationalStatus,
    RadarStartConfig,
    validate_service_name,
)
from off_key_core.utils.mqtt_topics import (
    mqtt_topic_filters_overlap,
    normalize_telemetry_topic_filters,
)
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...config.config import get_tactic_settings
from ...models.registry import ModelRegistryService
from ..radar_status import (
    TERMINAL_WORKLOAD_STATES,
    derive_operational_status,
)
from .radar_environment import (
    build_radar_config_fingerprint,
    build_radar_environment,
)
from .radar_lifecycle import RadarLifecycleController
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

    def __init__(
        self,
        session: AsyncSession,
        model_registry: ModelRegistryService,
        *,
        workloads: RadarWorkloadManager | None = None,
    ):
        self.session: AsyncSession = session
        self._workloads = workloads
        self.model_registry = model_registry
        logger.info("RadarOrchestrationService initialized.")

    @property
    def workloads(self):
        if self._workloads is None:
            self._workloads = RadarWorkloadManager(get_async_docker())
        return self._workloads

    @workloads.setter
    def workloads(self, value):
        self._workloads = value

    async def create_radar_service(
        self,
        config: RadarStartConfig,
        *,
        deployment_revision: str | None = None,
        activation_id: str | None = None,
        execution_service_id: str | None = None,
    ) -> MonitoringService:
        """Claim catalog sensors and launch the validated RADAR configuration."""
        if (
            (
                config.pipeline is not None
                or config.runtime_image is not None
                or config.mqtt_config.model_dump()
            )
            and activation_id is None
            and deployment_revision is None
        ):
            raise ValueError(
                "Internal launch settings require a pipeline activation or deployment"
            )
        mqtt_topics = config.mqtt_topics
        container_name = config.container_name
        await lock_collection_configuration(self.session)
        await require_application_writes(
            self.session, deployment_revision=deployment_revision
        )
        activation = await self._activation_for_launch(
            config, activation_id, execution_service_id
        )
        collection_fingerprint = await self._collection_fingerprint(mqtt_topics)
        if (
            activation_id is not None
            and activation.collection_fingerprint != collection_fingerprint
        ):
            raise ValueError("Monitoring inputs changed since preflight")
        await self._assert_topics_available(
            mqtt_topics=mqtt_topics,
            container_name=container_name,
            activation_id=activation_id,
        )
        db_service_id = execution_service_id or str(uuid.uuid4())
        env_vars = build_radar_environment(
            service_id=db_service_id,
            config=config,
            model_registry=self.model_registry,
        )
        env_vars["RADAR_COLLECTION_FINGERPRINT"] = collection_fingerprint
        config_fingerprint = build_radar_config_fingerprint(env_vars)

        # Check if service with this name already exists
        query = select(MonitoringService).where(
            MonitoringService.container_name == container_name
        )
        result = await self.session.execute(query)
        existing_service = result.scalars().first()

        if existing_service:
            if (
                getattr(existing_service, "config_fingerprint", None)
                and existing_service.status
            ):
                return await self._resume_managed_service(
                    existing_service, config_fingerprint
                )
            resolved_service = await self._resolve_existing_service_request(
                existing_service=existing_service,
                container_name=container_name,
                mqtt_topics=mqtt_topics,
                strategy=config.monitoring.strategy,
                model_type=config.monitoring.model_type,
                config_fingerprint=config_fingerprint,
                deployment_revision=deployment_revision,
            )
            if resolved_service:
                return resolved_service
            # A legacy inspection/removal deliberately ended its transaction.
            # Validate the prepared launch again after reacquiring the claim lock.
            await lock_collection_configuration(self.session)
            await require_application_writes(
                self.session, deployment_revision=deployment_revision
            )
            if (
                await self._collection_fingerprint(mqtt_topics)
                != collection_fingerprint
            ):
                raise ValueError(
                    "Monitoring inputs changed during workload inspection; retry start"
                )
            await self._assert_topics_available(
                mqtt_topics=mqtt_topics,
                container_name=container_name,
                activation_id=activation_id,
            )

        # Commit desired state and its sensor claim before any external mutation.
        # Even cancellation or a lost Docker reply now leaves a recoverable owner.
        env_vars["RADAR_LIFECYCLE_VERSION"] = "1"
        service_record = MonitoringService(
            id=db_service_id,
            container_id=None,
            container_name=container_name,
            mqtt_topic=mqtt_topics,
            created_at=datetime.now(),
            status=True,
            desired_state="running",
            lifecycle_version=1,
            config_fingerprint=config_fingerprint,
            collection_fingerprint=env_vars["RADAR_COLLECTION_FINGERPRINT"],
            operational_stage="starting",
            operational_status=RadarOperationalStatus(stage="starting").model_dump(
                mode="json", exclude_none=True
            ),
            operational_updated_at=None,
            launch_config=config.model_dump(mode="json")
            | {
                "monitoring": json.loads(env_vars["RADAR_MONITORING_CONFIG"]),
                "mqtt_config": config.mqtt_config.model_dump()
                | {
                    "qos": int(env_vars["RADAR_SUBSCRIPTION_QOS"]),
                    "client_id_prefix": env_vars["RADAR_MQTT_CLIENT_ID_PREFIX"],
                },
            },
        )
        try:
            self.session.add(service_record)
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            raise
        return await RadarLifecycleController(
            self.session, self.workloads
        ).complete_creation(db_service_id)

    async def _activation_for_launch(self, config, activation_id, service_id):
        if activation_id is None:
            return None
        from off_key_core.db.models import PipelineActivation, PipelineRun

        activation = await self.session.get(
            PipelineActivation, activation_id, populate_existing=True
        )
        run = await self.session.get(PipelineRun, config.pipeline.run_id)
        if (
            activation is None
            or activation.service_id != service_id
            or activation.phase != "starting"
            or activation.cancel_requested
            or run is None
            or run.ended_at is not None
        ):
            raise ValueError("Pipeline activation no longer owns a starting run")
        if activation.launch_config != config.model_dump(mode="json"):
            raise ValueError("Pipeline launch differs from its persisted activation")
        return activation

    async def _collection_fingerprint(self, topics):
        return await monitoring_collection_fingerprint(self.session, topics)

    async def _assert_topics_available(
        self,
        *,
        mqtt_topics: list[str],
        container_name: str,
        activation_id: str | None = None,
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
        activations = await self._pipeline_claims(mqtt_topics, activation_id)
        limit = get_tactic_settings().config.radar_max_active_monitors
        activation_targets = {item.service_id for item in activations}
        predecessor_ids = {item.predecessor_service_id for item in activations}
        owner_ids = {
            item.id for item in active_services if item.id not in predecessor_ids
        } | activation_targets
        if (
            len(owner_ids) >= limit
            and activation_id is None
            and not any(
                service.container_name == container_name for service in active_services
            )
        ):
            raise ValueError(
                f"RADAR capacity reached ({limit} active or pending monitors). "
                "Stop a monitor or increase the operator capacity limit."
            )
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

    async def _pipeline_claims(self, topics, activation_id):
        activations = await pending_activations(self.session)
        for activation in activations:
            if activation.id == activation_id:
                continue
            if any(
                mqtt_topic_filters_overlap(requested, claimed)
                for requested in topics
                for claimed in activation.claim_topics
            ):
                raise ValueError(
                    "A pending pipeline activation reserves requested inputs"
                )
        return activations

    async def _reconcile_active_topic_claims(self) -> list[MonitoringService]:
        result = await self.session.execute(
            select(MonitoringService).where(monitor_claim_condition())
        )
        return list(result.scalars().all())

    async def _resume_managed_service(self, service, config_fingerprint):
        if service.desired_state != "running" or service.stop_requested_at is not None:
            raise ValueError(f"RADAR service '{service.container_name}' is stopping")
        if service.config_fingerprint != config_fingerprint:
            raise ValueError(
                f"RADAR service name '{service.container_name}' already belongs "
                "to a running service with a different RADAR configuration."
            )
        service_id = service.id
        await self.session.commit()
        return await RadarLifecycleController(
            self.session, self.workloads
        ).complete_creation(service_id)

    async def _resolve_existing_service_request(
        self,
        *,
        existing_service: MonitoringService,
        container_name: str,
        mqtt_topics: list[str],
        strategy: str,
        model_type: str,
        config_fingerprint: str,
        deployment_revision: str | None = None,
    ) -> MonitoringService | None:
        """Reuse a matching live workload or clear a stale row before recreation."""
        if existing_service.stop_requested_at is not None:
            raise ValueError(
                f"RADAR service '{container_name}' is stopping after a "
                "collection change. "
                "Wait for it to stop before restarting."
            )
        service_id, workload_id = existing_service.id, existing_service.container_id
        version = getattr(existing_service, "lifecycle_version", 1)
        await self.session.commit()
        docker_status, labels = await self.workloads.get_status_and_labels(
            workload_id or ""
        )
        await lock_collection_configuration(self.session)
        await require_application_writes(
            self.session, deployment_revision=deployment_revision
        )
        current = await self.session.get(
            MonitoringService, service_id, with_for_update=True, populate_existing=True
        )
        if (
            current is None
            or current.container_id != workload_id
            or getattr(current, "lifecycle_version", 1) != version
            or current.stop_requested_at is not None
        ):
            raise ValueError(
                "RADAR workload changed during inspection; retry the request"
            )
        existing_service = current
        if docker_status != "running" and docker_status not in TERMINAL_WORKLOAD_STATES:
            raise ValueError(
                f"RADAR service name '{container_name}' already exists, but "
                "its workload is not confirmed stopped "
                f"(Docker status: {docker_status}). "
                "Wait for the existing workload or stop it before retrying."
            )

        if docker_status != "running":
            if not await self._delete_service(existing_service):
                raise ValueError(
                    "RADAR workload removal is pending; retry after it stops"
                )
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

        self._assert_existing_configuration(
            existing_service,
            labels,
            container_name,
            mqtt_topics,
            config_fingerprint,
            strategy,
            model_type,
        )
        logger.info("Reused existing RADAR service %s", container_name)
        return existing_service

    @staticmethod
    def _assert_existing_configuration(
        existing_service,
        labels,
        container_name,
        mqtt_topics,
        config_fingerprint,
        strategy,
        model_type,
    ):
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
            await lock_execution_records(self.session, service_ids)
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
        from off_key_core.db.models import PipelineRun
        from sqlalchemy import update

        await self.session.execute(
            update(PipelineRun)
            .where(
                PipelineRun.service_id.in_(service_ids), PipelineRun.ended_at.is_(None)
            )
            .values(status="stopped", ended_at=datetime.now(UTC))
        )

        await self.session.execute(
            delete(MqttTopic).where(MqttTopic.service_id.in_(service_ids))
        )
        delete_result = await self.session.execute(
            delete(MonitoringService).where(MonitoringService.id.in_(service_ids))
        )
        return int(delete_result.rowcount or 0)

    async def _delete_service(self, service: MonitoringService) -> bool:
        try:
            if service.desired_state != "deleted" or service.stop_requested_at is None:
                service.desired_state = "deleted"
                service.lifecycle_version = (
                    getattr(service, "lifecycle_version", None) or 1
                ) + 1
                service.stop_requested_at = datetime.now(UTC)
            service_id, workload_id = service.id, service.container_id
            version = service.lifecycle_version
            await self.session.commit()
            if getattr(service, "config_fingerprint", None):
                removed_workload = await self.workloads.remove_intent(
                    service_id, workload_id
                )
            else:
                removed_workload = await self.workloads.remove(workload_id)
            await lock_execution_records(self.session, [service_id])
            current = await self.session.get(
                MonitoringService,
                service_id,
                with_for_update=True,
                populate_existing=True,
            )
            if current is None:
                await self.session.commit()
                return True
            if (
                current.lifecycle_version != version
                or current.desired_state != "deleted"
            ):
                await self.session.rollback()
                return False
            deleted_rows = await self._delete_service_rows_by_ids([service_id])
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
        await lock_collection_configuration(self.session)
        await require_application_writes(self.session)
        cancelled_activation = await self._cancel_pipeline_activations(service_id)
        stmt = select(MonitoringService).where(MonitoringService.id == service_id)
        result = await self.session.execute(stmt)
        service = result.scalars().first()

        if not service:
            if cancelled_activation:
                await self.session.commit()
                return True
            logger.warning("No RADAR service found with id: %s", service_id)
            return False

        return await self._delete_service(service)

    async def _cancel_pipeline_activations(self, service_id: str) -> bool:
        affected = [
            item
            for item in await pending_activations(self.session)
            if item.service_id == service_id
            or item.predecessor_service_id == service_id
        ]
        for activation in affected:
            activation.cancel_requested = True
            activation.updated_at = datetime.now(UTC)
        return bool(affected)

    async def stop_radar_service(
        self,
        container_name: str | None = None,
        container_id: str | None = None,
        *,
        deployment_revision: str | None = None,
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

        await lock_collection_configuration(self.session)
        await require_application_writes(
            self.session, deployment_revision=deployment_revision
        )

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

        await self._cancel_pipeline_activations(service.id)
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

    async def rename_radar_service(self, service_id: str, display_name: str) -> bool:
        """Persist a presentation name without changing the workload or its inputs."""
        display_name = validate_service_name(display_name)
        await lock_collection_configuration(self.session)
        await require_application_writes(self.session)
        result = await self.session.execute(
            select(MonitoringService)
            .where(MonitoringService.id == service_id)
            .with_for_update()
        )
        service = result.scalars().first()
        if service is None:
            return False
        service.launch_config = {
            **(service.launch_config or {}),
            "display_name": display_name,
        }
        await self.session.commit()
        return True

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
