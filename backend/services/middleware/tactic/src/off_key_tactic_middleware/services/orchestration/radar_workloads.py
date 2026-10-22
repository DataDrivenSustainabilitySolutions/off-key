"""Docker workload lifecycle operations for TACTIC-managed RADAR instances."""

import asyncio
import time
from contextlib import suppress
from functools import lru_cache
from typing import Any

import docker
from docker.types import Resources, RestartPolicy, SecretReference, ServiceMode
from off_key_core.config.logs import logger

from ...config.config import get_tactic_settings
from ...facades.docker import (
    AsyncDocker,
    _extract_latest_workload_state,
    should_fallback_to_container,
)
from .radar_environment import (
    build_radar_config_fingerprint,
    build_radar_controller_identity,
    build_radar_workload_labels,
)

MANAGED_BY_TACTIC_LABEL = "managed_by=tactic"
RADAR_SERVICE_TYPE_LABEL = "service_type=radar"

_SWARM_CACHE_TTL_SECONDS = 30.0
_swarm_manager_cache: tuple[bool, float] | None = None


@lru_cache(maxsize=1)
def get_async_docker() -> AsyncDocker:
    """Create the shared Docker facade lazily."""
    return AsyncDocker()


class RadarWorkloadManager:
    """Create, inspect, and remove RADAR Docker workloads."""

    def __init__(self, async_docker: AsyncDocker):
        self.async_docker = async_docker

    async def find(self, service_id: str) -> Any | None:
        """Resolve the durable Docker name, including unknown create outcomes."""
        name = f"radar-{service_id}"
        try:
            return await self.async_docker.run(
                self.async_docker.client.services.get, name
            )
        except docker.errors.NotFound:
            pass
        except Exception as exc:
            if not should_fallback_to_container(exc):
                raise
        try:
            return await self.async_docker.run(
                self.async_docker.client.containers.get, name
            )
        except docker.errors.NotFound:
            return None

    async def ensure(self, service_id: str, environment: dict[str, str]) -> Any:
        """Idempotently create or adopt one workload for a persisted generation."""
        workload = await self.find(service_id)
        if workload is None:
            try:
                workload = await self.create(service_id, environment)
            except docker.errors.APIError as exc:
                if exc.status_code != 409:
                    raise
                # Another controller or a previously timed-out request won.
                workload = await self.find(service_id)
                if workload is None:
                    raise
        attrs = getattr(workload, "attrs", {}) or {}
        labels = (
            attrs.get("Spec", {}).get("Labels")
            or attrs.get("Config", {}).get("Labels")
            or {}
        )
        expected = {
            "managed_by": "tactic",
            "service_type": "radar",
            "radar_service_id": service_id,
            "radar_lifecycle_version": environment["RADAR_LIFECYCLE_VERSION"],
            "radar_config_fingerprint": build_radar_config_fingerprint(environment),
            "radar_controller_id": build_radar_controller_identity(
                environment["RADAR_DATABASE_URL"]
            ),
        }
        if any(labels.get(key) != value for key, value in expected.items()):
            raise RuntimeError(
                "Existing RADAR workload does not match its persisted intent"
            )
        return workload

    async def remove_intent(self, service_id: str, workload_id: str | None) -> bool:
        """Remove an attached worker and any unknown outcome at its durable name."""
        removed = await self.remove(workload_id)
        workload = await self.find(service_id)
        if workload is not None:
            attrs = getattr(workload, "attrs", {}) or {}
            labels = (
                attrs.get("Spec", {}).get("Labels")
                or attrs.get("Config", {}).get("Labels")
                or {}
            )
            if labels.get("radar_service_id") != service_id:
                raise RuntimeError(
                    "Refusing to remove a RADAR workload with a different owner"
                )
            removed = await self.remove(workload.id) or removed
        return removed

    async def create(self, service_id: str, environment: dict[str, str]) -> Any:
        """Create a Swarm service when available, otherwise a container."""
        production = environment.get("ENVIRONMENT") == "production"
        if await self._is_swarm_manager():
            try:
                return await self._create_swarm_service(service_id, environment)
            except Exception as exc:
                if production or not should_fallback_to_container(exc):
                    raise
                logger.warning(
                    "Swarm RADAR creation failed; falling back to container mode: %s",
                    exc,
                )

        if production:
            raise RuntimeError(
                "Production RADAR requires a Swarm manager and mounted secrets"
            )
        return await self._create_container(service_id, environment)

    async def _is_swarm_manager(self) -> bool:
        """Return a short-lived cached view of Docker Swarm manager status."""
        global _swarm_manager_cache
        now = time.monotonic()
        if _swarm_manager_cache is not None:
            cached_result, expiry = _swarm_manager_cache
            if now < expiry:
                return cached_result

        try:
            info = await self.async_docker.run(self.async_docker.client.info)
            swarm = info.get("Swarm", {})
            result = str(swarm.get("LocalNodeState", "")).lower() == "active" and bool(
                swarm.get("ControlAvailable")
            )
        except Exception as exc:
            logger.warning("Failed to detect Swarm mode; assuming non-Swarm: %s", exc)
            result = False

        _swarm_manager_cache = (result, now + _SWARM_CACHE_TTL_SECONDS)
        return result

    async def _create_swarm_service(
        self,
        service_id: str,
        environment: dict[str, str],
    ) -> Any:
        tactic_config = get_tactic_settings().config
        docker_config = tactic_config.docker
        budget = docker_config.resource_budget
        service_kwargs: dict[str, Any] = {
            "name": f"radar-{service_id}",
            "labels": build_radar_workload_labels(
                environment=environment,
                radar_image=environment.get(
                    "RADAR_RUNTIME_IMAGE", tactic_config.radar_image
                ),
            ),
            "image": environment.get("RADAR_RUNTIME_IMAGE", tactic_config.radar_image),
            "env": environment,
            "command": ["/app/bin/python", "-m", "off_key_mqtt_radar"],
            "mode": ServiceMode("replicated", replicas=1),
            "restart_policy": RestartPolicy(
                condition=docker_config.default_restart_policy,
                max_attempts=docker_config.default_restart_max_attempts,
            ),
            "networks": [
                docker_config.default_network,
                *docker_config.additional_networks,
            ],
            "resources": Resources(
                cpu_limit=budget.cpu_limit_nanos,
                mem_limit=budget.memory_limit_bytes,
                cpu_reservation=budget.cpu_reservation_nanos,
                mem_reservation=budget.memory_reservation_bytes,
            ),
        }
        if docker_config.default_constraints:
            service_kwargs["constraints"] = docker_config.default_constraints

        if environment.get("ENVIRONMENT") == "production":
            template_name = get_tactic_settings().TACTIC_RADAR_SECRET_SERVICE
            if not template_name:
                raise RuntimeError(
                    "TACTIC_RADAR_SECRET_SERVICE is required in production"
                )
            template = await self.async_docker.run(
                self.async_docker.client.services.get, template_name
            )
            container_spec = template.attrs["Spec"]["TaskTemplate"]["ContainerSpec"]
            references = container_spec.get("Secrets", [])
            required = {"EMQX_CA_CERT", "RADAR_MQTT_API_KEY", "RADAR_CHECKPOINT_SECRET"}
            by_target = {
                reference["File"]["Name"]: reference for reference in references
            }
            if not required <= by_target.keys():
                raise RuntimeError("Production RADAR secret template is incomplete")
            service_kwargs["secrets"] = [
                SecretReference(
                    secret_id=by_target[target]["SecretID"],
                    secret_name=by_target[target]["SecretName"],
                    filename=target,
                    uid=by_target[target]["File"].get("UID", "0"),
                    gid=by_target[target]["File"].get("GID", "0"),
                    mode=by_target[target]["File"].get("Mode", 0o444),
                )
                for target in sorted(required)
            ]

        return await self.async_docker.run(
            self.async_docker.client.services.create,
            **service_kwargs,
        )

    async def _create_container(
        self,
        service_id: str,
        environment: dict[str, str],
    ) -> Any:
        tactic_config = get_tactic_settings().config
        docker_config = tactic_config.docker
        budget = docker_config.resource_budget
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

        container = await self.async_docker.run(
            self.async_docker.client.containers.run,
            name=f"radar-{service_id}",
            labels=build_radar_workload_labels(
                environment=environment,
                radar_image=environment.get(
                    "RADAR_RUNTIME_IMAGE", tactic_config.radar_image
                ),
            ),
            image=environment.get("RADAR_RUNTIME_IMAGE", tactic_config.radar_image),
            environment=environment,
            command=["/app/bin/python", "-m", "off_key_mqtt_radar"],
            detach=True,
            network=docker_config.default_network,
            restart_policy=restart_policy,
            mem_limit=budget.memory_limit_bytes,
            mem_reservation=budget.memory_reservation_bytes,
            nano_cpus=budget.cpu_limit_nanos,
        )

        # containers.run only attaches one network; connect the rest (e.g. the app
        # network for Postgres) so the workload matches the Swarm multi-network path.
        for network_name in docker_config.additional_networks:
            network = await self.async_docker.run(
                self.async_docker.client.networks.get,
                network_name,
            )
            await self.async_docker.run(network.connect, container)

        return container

    async def validate_started(self, docker_workload: Any) -> None:
        """Fail when a newly created RADAR workload exits or is rejected."""
        workload_id = getattr(docker_workload, "id", None)
        if not workload_id:
            return

        grace_seconds = get_tactic_settings().config.radar_startup_grace_seconds
        if grace_seconds > 0:
            await asyncio.sleep(grace_seconds)

        try:
            docker_service = await self.async_docker.run(
                self.async_docker.client.services.get,
                workload_id,
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
                self.async_docker.client.containers.get,
                workload_id,
            )
            await self.async_docker.run(docker_container.reload)
        except docker.errors.NotFound as exc:
            raise RuntimeError(
                f"RADAR workload {workload_id} disappeared during startup"
            ) from exc

        status = str(getattr(docker_container, "status", "") or "unknown").lower()
        if status not in {"exited", "dead", "restarting"}:
            return

        logs = await self._get_container_log_tail(docker_container)
        message = (
            f"RADAR workload {workload_id} failed during startup (status={status})"
        )
        if logs:
            message = f"{message}. Recent logs:\n{logs}"
        raise RuntimeError(message)

    @staticmethod
    def _raise_for_failed_swarm_task(
        workload_id: str,
        tasks: list[dict[str, Any]],
    ) -> None:
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

    async def remove(self, workload_id: str | None) -> bool:
        """Confirm task termination before releasing a workload's sensor claim."""
        if not workload_id:
            return False
        swarm_supported = True
        try:
            service = await self.async_docker.run(
                self.async_docker.client.services.get, workload_id
            )
        except docker.errors.NotFound:
            pass
        except Exception as exc:
            if not should_fallback_to_container(exc):
                raise
            swarm_supported = False
        else:
            await self._stop_swarm_tasks(service)
            with suppress(docker.errors.NotFound):
                await self.async_docker.run(service.remove)
            return True

        try:
            container = await self.async_docker.run(
                self.async_docker.client.containers.get, workload_id
            )
            await self.async_docker.run(container.remove, force=True)
            return True
        except docker.errors.NotFound:
            if swarm_supported:
                await self._wait_for_task_shutdown(
                    lambda: self._remaining_service_tasks(workload_id)
                )
            return False

    async def _stop_swarm_tasks(self, service: Any) -> None:
        """Keep the service inspectable until every task acknowledges shutdown."""
        try:
            await self.async_docker.run(service.scale, 0)
            await self._wait_for_task_shutdown(
                lambda: self.async_docker.run(service.tasks)
            )
        except docker.errors.NotFound:
            await self._wait_for_task_shutdown(
                lambda: self._remaining_service_tasks(service.id)
            )

    async def _remaining_service_tasks(self, service_id):
        try:
            return await self.async_docker.run(
                self.async_docker.client.api.tasks, filters={"service": service_id}
            )
        except docker.errors.NotFound:
            # Docker resolves service filters against existing services and can
            # return404 while retiring task records still exist in the task list.
            tasks = await self.async_docker.run(self.async_docker.client.api.tasks)
            return [task for task in tasks if task.get("ServiceID") == service_id]

    async def _wait_for_task_shutdown(self, query):
        terminal = {"shutdown", "complete", "completed", "failed", "rejected", "remove"}
        try:
            async with asyncio.timeout(
                get_tactic_settings().config.radar_stop_timeout_seconds
            ):
                while True:
                    tasks = await query()
                    if all(
                        isinstance(task, dict)
                        and isinstance(task.get("Status"), dict)
                        and str(task["Status"].get("State", "")).lower() in terminal
                        for task in tasks
                    ):
                        return
                    await asyncio.sleep(0.1)
        except TimeoutError:
            raise RuntimeError(
                "RADAR tasks have not stopped; the sensor claim is retained"
            ) from None

    @staticmethod
    def _managed_label_filters() -> dict[str, list[str]]:
        return {"label": [MANAGED_BY_TACTIC_LABEL, RADAR_SERVICE_TYPE_LABEL]}

    async def list_managed_ids(self, *, controller_id: str | None = None) -> set[str]:
        """List every managed RADAR service and container ID."""
        filters = self._managed_label_filters()
        if controller_id is not None:
            filters["label"].append(f"radar_controller_id={controller_id}")
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

    async def get_status_and_labels(
        self,
        workload_id: str,
    ) -> tuple[str, dict[str, str]]:
        """Return normalized status and labels for a service or container."""
        if not workload_id:
            return "no_container_id", {}

        try:
            try:
                docker_service = await self.async_docker.run(
                    self.async_docker.client.services.get,
                    workload_id,
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
                        workload_id,
                        exc,
                    )
                    return "error", {}
                logger.debug(
                    "Skipping Swarm workload metadata lookup for %s: %s",
                    workload_id,
                    exc,
                )

            docker_container = await self.async_docker.run(
                self.async_docker.client.containers.get,
                workload_id,
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
                "Error checking Docker workload metadata for %s: %s",
                workload_id,
                exc,
            )
            return "error", {}
