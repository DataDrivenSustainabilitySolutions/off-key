"""Swarm service lifecycle operations for TACTIC-managed RADAR instances.

Every deployment, local development included, runs RADAR as Swarm services.
"""

import asyncio
from contextlib import suppress
from functools import lru_cache
from typing import Any

import docker
from docker.types import Resources, RestartPolicy, SecretReference, ServiceMode
from off_key_core.config.logs import logger

from ...config.config import get_tactic_settings
from ...facades.docker import AsyncDocker, _extract_latest_workload_state
from .radar_environment import (
    build_radar_config_fingerprint,
    build_radar_controller_identity,
    build_radar_workload_labels,
)

MANAGED_BY_TACTIC_LABEL = "managed_by=tactic"
RADAR_SERVICE_TYPE_LABEL = "service_type=radar"


@lru_cache(maxsize=1)
def get_async_docker() -> AsyncDocker:
    """Create the shared Docker facade lazily."""
    return AsyncDocker()


class RadarWorkloadManager:
    """Create, inspect, and remove RADAR Swarm services."""

    def __init__(self, async_docker: AsyncDocker):
        self.async_docker = async_docker

    async def find(self, service_id: str) -> Any | None:
        """Resolve the durable Docker name, including unknown create outcomes."""
        try:
            return await self.async_docker.run(
                self.async_docker.client.services.get, f"radar-{service_id}"
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
        labels = _labels(workload)
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
            if _labels(workload).get("radar_service_id") != service_id:
                raise RuntimeError(
                    "Refusing to remove a RADAR workload with a different owner"
                )
            removed = await self.remove(workload.id) or removed
        return removed

    async def create(self, service_id: str, environment: dict[str, str]) -> Any:
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
        except docker.errors.NotFound as exc:
            raise RuntimeError(
                f"RADAR workload {workload_id} disappeared during startup"
            ) from exc
        tasks = await self.async_docker.run(docker_service.tasks)
        self._raise_for_failed_swarm_task(workload_id, tasks)

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

    async def remove(self, workload_id: str | None) -> bool:
        """Confirm task termination before releasing a workload's sensor claim."""
        if not workload_id:
            return False
        try:
            service = await self.async_docker.run(
                self.async_docker.client.services.get, workload_id
            )
        except docker.errors.NotFound:
            await self._wait_for_task_shutdown(
                lambda: self._remaining_service_tasks(workload_id)
            )
            return False
        await self._stop_swarm_tasks(service)
        with suppress(docker.errors.NotFound):
            await self.async_docker.run(service.remove)
        return True

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
        """List every managed RADAR service ID."""
        filters = self._managed_label_filters()
        if controller_id is not None:
            filters["label"].append(f"radar_controller_id={controller_id}")
        docker_services = await self.async_docker.run(
            self.async_docker.client.services.list,
            filters=filters,
        )
        return {service.id for service in docker_services if service.id}

    async def get_status_and_labels(
        self,
        workload_id: str,
    ) -> tuple[str, dict[str, str]]:
        """Return normalized status and labels for a service."""
        if not workload_id:
            return "no_container_id", {}

        try:
            docker_service = await self.async_docker.run(
                self.async_docker.client.services.get,
                workload_id,
            )
            tasks = await self.async_docker.run(docker_service.tasks)
            status = _extract_latest_workload_state(tasks)
            labels = _labels(docker_service)
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


def _labels(workload: Any) -> dict[str, str]:
    attrs = getattr(workload, "attrs", {}) or {}
    return attrs.get("Spec", {}).get("Labels") or {}
