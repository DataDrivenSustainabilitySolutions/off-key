"""Docker workload lifecycle operations for TACTIC-managed RADAR instances."""

import asyncio
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Any

import docker
from docker.types import Resources, RestartPolicy, ServiceMode
from off_key_core.config.logs import logger

from ...config.config import get_tactic_settings
from ...facades.docker import (
    AsyncDocker,
    _extract_latest_workload_state,
    should_fallback_to_container,
    with_workload_fallback,
)
from .radar_environment import build_radar_workload_labels

MANAGED_BY_TACTIC_LABEL = "managed_by=tactic"
RADAR_SERVICE_TYPE_LABEL = "service_type=radar"

_SWARM_CACHE_TTL_SECONDS = 30.0
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
    """Create the shared Docker facade lazily."""
    return AsyncDocker()


def _parse_memory_string(memory_string: str) -> int:
    """Convert a Docker memory-size string to bytes."""
    normalized = memory_string.lower().strip()
    if not normalized:
        return _DEFAULT_MEMORY_BYTES
    if normalized.isdigit():
        return int(normalized)

    for suffix, multiplier in _MEMORY_SIZE_MULTIPLIERS.items():
        if not normalized.endswith(suffix):
            continue
        number_part = normalized[: -len(suffix)].strip()
        try:
            return int(float(number_part) * multiplier)
        except ValueError:
            break

    logger.warning(
        "Invalid Docker memory limit %r; using the 512 MiB default",
        memory_string,
    )
    return _DEFAULT_MEMORY_BYTES


class RadarWorkloadManager:
    """Create, inspect, and remove RADAR Docker workloads."""

    def __init__(self, async_docker: AsyncDocker):
        self.async_docker = async_docker

    async def create(self, service_id: str, environment: dict[str, str]) -> Any:
        """Create a Swarm service when available, otherwise a container."""
        if await self._is_swarm_manager():
            try:
                return await self._create_swarm_service(service_id, environment)
            except Exception as exc:
                if not should_fallback_to_container(exc):
                    raise
                logger.warning(
                    "Swarm RADAR creation failed; falling back to container mode: %s",
                    exc,
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
        service_kwargs: dict[str, Any] = {
            "name": f"radar-{service_id}",
            "labels": build_radar_workload_labels(
                environment=environment,
                radar_image=tactic_config.radar_image,
            ),
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

    async def _create_container(
        self,
        service_id: str,
        environment: dict[str, str],
    ) -> Any:
        tactic_config = get_tactic_settings().config
        docker_config = tactic_config.docker
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

        return await self.async_docker.run(
            self.async_docker.client.containers.run,
            name=f"radar-{service_id}",
            labels=build_radar_workload_labels(
                environment=environment,
                radar_image=tactic_config.radar_image,
            ),
            image=tactic_config.radar_image,
            environment=environment,
            command=["/app/bin/python", "-m", "off_key_mqtt_radar"],
            detach=True,
            network=docker_config.default_network,
            restart_policy=restart_policy,
            mem_limit=_parse_memory_string(docker_config.default_memory_limit),
            nano_cpus=int(float(docker_config.default_cpu_limit) * 1_000_000_000),
        )

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

    async def resolve_operation(
        self,
        workload_id: str,
        on_service: Callable[[Any], Any],
        on_container: Callable[[Any], Any],
    ) -> Any:
        """Apply an operation to a Swarm service or fallback container."""
        return await with_workload_fallback(
            self.async_docker,
            workload_id,
            on_service=on_service,
            on_container=on_container,
        )

    async def remove(self, workload_id: str | None) -> bool:
        """Remove a workload, returning whether it still existed."""
        if not workload_id:
            return False
        try:
            await self.resolve_operation(
                workload_id,
                on_service=lambda service: service.remove(),
                on_container=lambda container: container.remove(force=True),
            )
            return True
        except docker.errors.NotFound:
            return False

    async def remove_after_failure(self, docker_workload: Any) -> None:
        """Best-effort cleanup after persistence or startup fails."""
        workload_id = getattr(docker_workload, "id", None)
        if not workload_id:
            return
        try:
            removed = await self.remove(workload_id)
            logger.info(
                "RADAR workload %s %s after failed service creation",
                workload_id,
                "removed" if removed else "already absent",
            )
        except Exception:
            logger.exception(
                "Failed to remove RADAR workload %s after service creation failure",
                workload_id,
            )

    @staticmethod
    def _managed_label_filters() -> dict[str, list[str]]:
        return {"label": [MANAGED_BY_TACTIC_LABEL, RADAR_SERVICE_TYPE_LABEL]}

    async def list_managed_ids(self) -> set[str]:
        """List every managed RADAR service and container ID."""
        filters = self._managed_label_filters()
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
