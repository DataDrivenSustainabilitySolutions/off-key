import asyncio
import time
from collections.abc import Callable
from typing import Any

import docker
from docker import DockerClient
from off_key_core.config.logs import log_performance, logger

from ..config.config import get_tactic_settings

_SWARM_FALLBACK_INDICATORS = (
    "cannot be used with services",
    "only networks scoped to the swarm can be used",
    "this node is not a swarm manager",
    "swarm mode",
)


def _extract_latest_workload_state(
    tasks: list[object], no_tasks_state: str = "no_tasks"
) -> str:
    task_items = [task for task in tasks if isinstance(task, dict)]
    if not task_items:
        return no_tasks_state
    latest = max(task_items, key=lambda task: str(task.get("CreatedAt", "")))
    status = latest.get("Status")
    if not isinstance(status, dict):
        status = {}
    return str(status.get("State", "unknown")).strip().lower()


class AsyncDocker:
    def __init__(self, docker_config=None):
        config = docker_config or get_tactic_settings().config.docker

        try:
            self.client = DockerClient(base_url=config.base_url)
            self.semaphore = asyncio.Semaphore(config.max_concurrent_calls)
            self.config = config
            logger.info(
                f"Docker client initialized successfully |"
                f" URL: {config.base_url} | "
                f"Max concurrent: {config.max_concurrent_calls}"
            )
        except Exception as e:
            logger.error(
                f"Failed to initialize Docker client |"
                f" URL: {config.base_url} | Error: {e!s}"
            )
            raise

    async def run(self, func: Callable, *args, **kwargs) -> Any:
        start_time = time.time()
        func_name = getattr(func, "__name__", "unknown_function")

        try:
            async with self.semaphore:
                logger.debug(f"Executing Docker operation: {func_name}")
                result = await asyncio.to_thread(func, *args, **kwargs)
                log_performance(f"docker_{func_name}", start_time)
                return result
        except Exception as e:
            logger.error(f"Docker operation failed: {func_name} | Error: {e!s}")
            raise

    def close(self) -> None:
        """Close the underlying Docker client and release resources."""
        if self.client:
            try:
                self.client.close()
                logger.debug("Docker client closed")
            except Exception as e:
                logger.warning(f"Error closing Docker client: {e}")


def should_fallback_to_container(exc: Exception) -> bool:
    if isinstance(exc, docker.errors.APIError) and exc.status_code in (400, 406, 503):
        return True
    text = str(exc).lower()
    return any(indicator in text for indicator in _SWARM_FALLBACK_INDICATORS)


async def get_workload_docker_status(
    async_docker: AsyncDocker, container_id: str
) -> str:
    """Return the running status of a Docker workload by ID.

    Tries Swarm services first (reads task state), then falls back to plain
    containers (reads container status). Both callers -- RadarOrchestrationService
    and RadarStatusReconciliationService -- delegate here to avoid duplicating the
    service->container probe-and-fallback logic.

    Returns:
        "running" | task state | "no_tasks" | "not_found" | "no_container_id"
        | "unknown" | "error"
    """
    if not container_id:
        return "no_container_id"
    try:
        try:
            docker_service = await async_docker.run(
                async_docker.client.services.get, container_id
            )
            tasks = await async_docker.run(docker_service.tasks)
            return _extract_latest_workload_state(tasks)
        except docker.errors.NotFound:
            pass
        except Exception as exc:
            if not should_fallback_to_container(exc):
                raise
            logger.debug(
                "Skipping Swarm service status lookup for workload %s: %s",
                container_id,
                exc,
            )

        docker_container = await async_docker.run(
            async_docker.client.containers.get, container_id
        )
        await async_docker.run(docker_container.reload)
        return docker_container.status or "unknown"
    except docker.errors.NotFound:
        return "not_found"
    except Exception as exc:
        logger.debug("Error checking Docker status for %s: %s", container_id, exc)
        return "error"


async def with_workload_fallback(
    async_docker: AsyncDocker,
    container_id: str,
    on_service: Callable[[Any], Any],
    on_container: Callable[[Any], Any],
) -> Any:
    """Resolve a Docker workload as swarm service first, then fallback to container."""
    try:
        docker_service = await async_docker.run(
            async_docker.client.services.get, container_id
        )
        return await async_docker.run(on_service, docker_service)
    except docker.errors.NotFound:
        pass
    except Exception as exc:
        if not should_fallback_to_container(exc):
            raise
        logger.debug(
            "Skipping Swarm service operation for workload %s: %s",
            container_id,
            exc,
        )

    docker_container = await async_docker.run(
        async_docker.client.containers.get, container_id
    )
    return await async_docker.run(on_container, docker_container)
