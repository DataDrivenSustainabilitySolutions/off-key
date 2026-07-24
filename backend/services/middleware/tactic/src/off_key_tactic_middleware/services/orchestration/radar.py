import asyncio
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from functools import lru_cache
from typing import Any

import docker
from docker.types import Resources, RestartPolicy, ServiceMode
from off_key_core.config.logs import logger
from off_key_core.db.models import MonitoringService, MqttTopic
from off_key_core.schemas.radar import RadarOperationalStatus
from off_key_core.utils.mqtt_topics import (
    mqtt_topic_filters_overlap,
    normalize_mqtt_topic_filters,
    normalize_static_monitoring_topics,
)
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...config.config import get_tactic_settings
from ...facades.docker import (
    AsyncDocker,
    _extract_latest_workload_state,
    should_fallback_to_container,
    with_workload_fallback,
)
from ...models.registry import ModelRegistryService
from ..radar_status import (
    TERMINAL_WORKLOAD_STATES,
    apply_terminal_operational_status,
    derive_operational_status,
)
from .radar_environment import (
    build_radar_config_fingerprint,
    build_radar_environment,
    build_radar_workload_labels,
)

MANAGED_BY_TACTIC_LABEL = "managed_by=tactic"
RADAR_SERVICE_TYPE_LABEL = "service_type=radar"

# Swarm manager status is stable over short windows: cache the result to avoid
# a docker.info() round-trip on every RADAR service creation request.
_SWARM_CACHE_TTL_SECONDS: float = 30.0
_swarm_manager_cache: tuple[bool, float] | None = None
_DEFAULT_MEMORY_BYTES = 536_870_912
_MEMORY_SIZE_MULTIPLIERS = {
    "k": 1024,
    "m": 1024 * 1024,
    "g": 1024 * 1024 * 1024,
    "kb": 1024,
    "mb": 1024 * 1024,
    "gb": 1024 * 1024 * 1024,
}


@lru_cache(maxsize=1)
def get_async_docker() -> AsyncDocker:
    """Create Docker facade lazily to avoid import-time settings evaluation.

    Note:
        This function is cached. Tests that monkeypatch Docker behavior or related
        settings should clear the cache between cases.
    """
    return AsyncDocker()


def _parse_memory_string(memory_str: str) -> int:
    """
    Convert memory string (e.g., '512m', '1g', '1024') to bytes.

    Args:
        memory_str: Memory string with optional suffix (k, m, g)

    Returns:
        int: Memory in bytes
    """
    if not memory_str:
        return _DEFAULT_MEMORY_BYTES  # Default 512MB in bytes

    memory_str = memory_str.lower().strip()

    # If it's already a number, assume bytes
    if memory_str.isdigit():
        return int(memory_str)

    # Parse with suffixes
    for suffix, multiplier in _MEMORY_SIZE_MULTIPLIERS.items():
        if memory_str.endswith(suffix):
            number_part = memory_str[: -len(suffix)].strip()
            try:
                return int(float(number_part) * multiplier)
            except ValueError:
                logger.warning(
                    f"Invalid memory format: {memory_str}, using default 512MB"
                )
                return _DEFAULT_MEMORY_BYTES

    logger.warning(f"Unknown memory format: {memory_str}, using default 512MB")
    return _DEFAULT_MEMORY_BYTES


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
        self.async_docker: AsyncDocker = get_async_docker()
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
            docker_workload = await self._create_radar_workload(
                service_id=db_service_id,
                environment=env_vars,
            )
            await self._validate_radar_workload_started(docker_workload)

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
                await self._remove_created_workload_after_failure(docker_workload)
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
            docker_status, _ = await self._get_docker_status_and_labels(
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
        docker_status, labels = await self._get_docker_status_and_labels(
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

        existing_topics = normalize_mqtt_topic_filters(
            existing_service.mqtt_topic,
            require_charger_prefix=True,
            require_telemetry_topic=True,
        )
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

    async def _remove_created_workload_after_failure(
        self,
        docker_workload: Any,
    ) -> None:
        """Best-effort cleanup for workloads created before DB persistence failed."""
        workload_id = getattr(docker_workload, "id", None)
        if not workload_id:
            return
        try:
            await self._resolve_workload_operation(
                workload_id,
                on_service=lambda s: s.remove(),
                on_container=lambda c: c.remove(force=True),
            )
            logger.info(
                "Removed RADAR workload %s after failed service creation",
                workload_id,
            )
        except docker.errors.NotFound:
            logger.info(
                "RADAR workload %s already absent after failed service creation",
                workload_id,
            )
        except Exception:
            logger.exception(
                "Failed to remove RADAR workload %s after service creation failure",
                workload_id,
            )

    async def _is_swarm_manager(self) -> bool:
        """Return True when Docker engine is an active Swarm manager.

        Result is cached for _SWARM_CACHE_TTL_SECONDS so that burst RADAR
        creation does not issue a docker.info() call per service. The TTL is
        short enough to react to cluster topology changes within a reasonable
        window without retaining stale state indefinitely.
        """
        global _swarm_manager_cache
        now = time.monotonic()
        if _swarm_manager_cache is not None:
            cached_result, expiry = _swarm_manager_cache
            if now < expiry:
                return cached_result
        try:
            info = await self.async_docker.run(self.async_docker.client.info)
            swarm = info.get("Swarm", {})
            local_node_state = str(swarm.get("LocalNodeState", "")).lower()
            result = local_node_state == "active" and bool(
                swarm.get("ControlAvailable")
            )
        except Exception as exc:
            logger.warning("Failed to detect Swarm mode; assuming non-Swarm: %s", exc)
            result = False
        _swarm_manager_cache = (result, now + _SWARM_CACHE_TTL_SECONDS)
        return result

    async def _create_radar_workload(
        self,
        service_id: str,
        environment: dict[str, str],
    ) -> Any:
        """
        Create RADAR as a Swarm service when possible, otherwise as a Docker container.
        """
        if await self._is_swarm_manager():
            try:
                return await self._create_radar_swarm_service(
                    service_id=service_id,
                    environment=environment,
                )
            except Exception as exc:
                if not should_fallback_to_container(exc):
                    raise
                logger.warning(
                    "Swarm RADAR creation failed; falling back to container mode: %s",
                    exc,
                )

        return await self._create_radar_container(
            service_id=service_id,
            environment=environment,
        )

    async def _create_radar_swarm_service(
        self,
        service_id: str,
        environment: dict[str, str],
    ) -> Any:
        """
        Helper method to create RADAR Docker service using Pydantic configuration.
        """
        # Get Docker configuration from Pydantic settings
        tactic_config = get_tactic_settings().config
        docker_config = tactic_config.docker

        labels = build_radar_workload_labels(
            environment=environment, radar_image=tactic_config.radar_image
        )

        service_kwargs = {
            "name": f"radar-{service_id}",
            "labels": labels,
            "image": tactic_config.radar_image,
            "env": environment,
            "command": ["/app/bin/python", "-m", "off_key_mqtt_radar"],
            "mode": ServiceMode("replicated", replicas=1),
            "restart_policy": RestartPolicy(
                condition=docker_config.default_restart_policy,
                max_attempts=docker_config.default_restart_max_attempts,
            ),
            "networks": [docker_config.default_network],
            "resources": Resources(
                cpu_limit=int(float(docker_config.default_cpu_limit) * 1_000_000_000),
                mem_limit=_parse_memory_string(docker_config.default_memory_limit),
            ),
        }

        if docker_config.default_constraints:
            service_kwargs["constraints"] = docker_config.default_constraints

        return await self.async_docker.run(
            self.async_docker.client.services.create,
            **service_kwargs,
        )

    async def _create_radar_container(
        self,
        service_id: str,
        environment: dict[str, str],
    ) -> Any:
        """Helper method to create RADAR Docker container in non-Swarm mode."""
        tactic_config = get_tactic_settings().config
        docker_config = tactic_config.docker

        labels = build_radar_workload_labels(
            environment=environment, radar_image=tactic_config.radar_image
        )

        restart_policy: dict[str, Any] = {
            "Name": docker_config.default_restart_policy,
        }
        if (
            docker_config.default_restart_policy == "on-failure"
            and docker_config.default_restart_max_attempts > 0
        ):
            restart_policy["MaximumRetryCount"] = (
                docker_config.default_restart_max_attempts
            )

        container_kwargs = {
            "name": f"radar-{service_id}",
            "labels": labels,
            "image": tactic_config.radar_image,
            "environment": environment,
            "command": ["/app/bin/python", "-m", "off_key_mqtt_radar"],
            "detach": True,
            "network": docker_config.default_network,
            "restart_policy": restart_policy,
            "mem_limit": _parse_memory_string(docker_config.default_memory_limit),
            "nano_cpus": int(float(docker_config.default_cpu_limit) * 1_000_000_000),
        }

        return await self.async_docker.run(
            self.async_docker.client.containers.run,
            **container_kwargs,
        )

    async def _validate_radar_workload_started(self, docker_workload: Any) -> None:
        """Fail service creation when RADAR exits or is rejected at startup."""
        workload_id = getattr(docker_workload, "id", None)
        if not workload_id:
            return

        grace_seconds = get_tactic_settings().config.radar_startup_grace_seconds
        if grace_seconds > 0:
            await asyncio.sleep(grace_seconds)

        try:
            docker_service = await self.async_docker.run(
                self.async_docker.client.services.get, workload_id
            )
            tasks = await self.async_docker.run(docker_service.tasks)
            self._raise_for_failed_swarm_task(workload_id, tasks)
            return
        except docker.errors.NotFound:
            pass
        except Exception as exc:
            if not should_fallback_to_container(exc):
                raise
            logger.debug(
                "Skipping Swarm startup validation for workload %s: %s",
                workload_id,
                exc,
            )

        try:
            docker_container = await self.async_docker.run(
                self.async_docker.client.containers.get, workload_id
            )
            await self.async_docker.run(docker_container.reload)
        except docker.errors.NotFound as exc:
            raise RuntimeError(
                f"RADAR workload {workload_id} disappeared during startup"
            ) from exc

        status = str(getattr(docker_container, "status", "") or "unknown").lower()
        if status in {"exited", "dead", "restarting"}:
            logs = await self._get_container_log_tail(docker_container)
            message = (
                f"RADAR workload {workload_id} failed during startup (status={status})"
            )
            if logs:
                message = f"{message}. Recent logs:\n{logs}"
            raise RuntimeError(message)

    @staticmethod
    def _raise_for_failed_swarm_task(workload_id: str, tasks: list[dict[str, Any]]):
        if not tasks:
            return
        task_items = [task for task in tasks if isinstance(task, dict)]
        if not task_items:
            return

        latest_task = max(task_items, key=lambda task: str(task.get("CreatedAt", "")))
        status = latest_task.get("Status")
        if not isinstance(status, dict):
            status = {}
        state = str(status.get("State", "") or "unknown").lower()
        if state not in {
            "complete",
            "failed",
            "rejected",
            "shutdown",
            "orphaned",
            "remove",
        }:
            return

        detail = status.get("Err") or status.get("Message") or "no task error"
        raise RuntimeError(
            f"RADAR workload {workload_id} failed during startup "
            f"(task_state={state}): {detail}"
        )

    async def _get_container_log_tail(self, docker_container: Any) -> str:
        raw_logs = await self.async_docker.run(docker_container.logs, tail=120)
        if isinstance(raw_logs, bytes):
            logs = raw_logs.decode("utf-8", errors="replace")
        else:
            logs = str(raw_logs or "")
        return logs.strip()[-4000:]

    async def _resolve_workload_operation(
        self,
        container_id: str,
        on_service: Callable[[Any], Any],
        on_container: Callable[[Any], Any],
    ) -> Any:
        """Apply operation to Swarm service or fallback container by ID."""
        return await with_workload_fallback(
            self.async_docker,
            container_id,
            on_service=on_service,
            on_container=on_container,
        )

    @staticmethod
    def _managed_radar_label_filters() -> dict[str, list[str]]:
        return {"label": [MANAGED_BY_TACTIC_LABEL, RADAR_SERVICE_TYPE_LABEL]}

    async def _list_managed_radar_workload_ids(self) -> set[str]:
        filters = self._managed_radar_label_filters()

        try:
            docker_services = await self.async_docker.run(
                self.async_docker.client.services.list,
                filters=filters,
            )
        except Exception as exc:
            if not should_fallback_to_container(exc):
                raise
            logger.info(
                "Skipping Swarm service cleanup because this Docker engine does "
                "not support Swarm services: %s",
                exc,
            )
            docker_services = []

        docker_containers = await self.async_docker.run(
            self.async_docker.client.containers.list,
            all=True,
            filters=filters,
        )

        service_ids = {service.id for service in docker_services if service.id}
        container_ids = {
            container.id for container in docker_containers if container.id
        }
        return service_ids | container_ids

    async def teardown_managed_radar_workloads(self) -> dict[str, int]:
        """
        Remove all TACTIC-managed RADAR Docker workloads and clear service records.

        Returns:
            Dict[str, int]: Cleanup summary counters.
        """
        managed_workload_ids = await self._list_managed_radar_workload_ids()
        target_ids = set(managed_workload_ids)

        removed_workloads = 0
        successfully_removed: set[str] = set()
        removal_failures: list[str] = []

        for workload_id in target_ids:
            try:
                await self._resolve_workload_operation(
                    workload_id,
                    on_service=lambda s: s.remove(),
                    on_container=lambda c: c.remove(force=True),
                )
                removed_workloads += 1
                successfully_removed.add(workload_id)
            except docker.errors.NotFound:
                # Workload already absent in Docker; DB row should still be cleaned up.
                successfully_removed.add(workload_id)
                continue
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

    async def _remove_workload_for_delete(self, container_id: str | None) -> bool:
        if not container_id:
            return False
        try:
            await self._resolve_workload_operation(
                container_id,
                on_service=lambda s: s.remove(),
                on_container=lambda c: c.remove(force=True),
            )
            return True
        except docker.errors.NotFound:
            return False

    async def _delete_service(self, service: MonitoringService) -> bool:
        try:
            removed_workload = await self._remove_workload_for_delete(
                service.container_id
            )
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

    async def _get_docker_status_and_labels(
        self, container_id: str
    ) -> tuple[str, dict[str, str]]:
        if not container_id:
            return "no_container_id", {}

        try:
            try:
                docker_service = await self.async_docker.run(
                    self.async_docker.client.services.get, container_id
                )
                tasks = await self.async_docker.run(docker_service.tasks)
                status = _extract_latest_workload_state(tasks)
                attrs = getattr(docker_service, "attrs", {}) or {}
                labels = attrs.get("Spec", {}).get("Labels", {}) or {}
                return status, {str(key): str(value) for key, value in labels.items()}
            except docker.errors.NotFound:
                pass
            except Exception as exc:
                if not should_fallback_to_container(exc):
                    logger.debug(
                        "Error checking Docker workload metadata for %s: %s",
                        container_id,
                        exc,
                    )
                    return "error", {}
                logger.debug(
                    "Skipping Swarm workload metadata lookup for %s: %s",
                    container_id,
                    exc,
                )

            docker_container = await self.async_docker.run(
                self.async_docker.client.containers.get, container_id
            )
            await self.async_docker.run(docker_container.reload)
            status = (
                str(getattr(docker_container, "status", "") or "unknown").lower()
                or "unknown"
            )
            attrs = getattr(docker_container, "attrs", {}) or {}
            labels = attrs.get("Config", {}).get("Labels", {}) or {}
            return status, {str(key): str(value) for key, value in labels.items()}
        except docker.errors.NotFound:
            return "not_found", {}
        except Exception as exc:
            logger.debug(
                "Error checking Docker workload metadata for %s: %s", container_id, exc
            )
            return "error", {}

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
                docker_status, labels = await self._get_docker_status_and_labels(
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
        docker_service_status, labels = await self._get_docker_status_and_labels(
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
