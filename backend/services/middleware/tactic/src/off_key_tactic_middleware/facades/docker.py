import asyncio
import time
from collections.abc import Callable, Sequence
from typing import Any

import docker.errors
from docker import DockerClient
from off_key_core.config.logs import log_performance, logger

from ..config.config import DockerConfig, get_tactic_settings

# Swarm task states after which a task no longer runs. Shutdown waits also accept
# "completed"; a startup check also treats an orphaned task as failed.
SWARM_TASK_DONE = frozenset({"shutdown", "complete", "failed", "rejected", "remove"})
SWARM_TASK_SHUTDOWN_DONE = SWARM_TASK_DONE | {"completed"}
SWARM_TASK_STARTUP_FAILED = SWARM_TASK_DONE | {"orphaned"}


def latest_task_status(tasks: Sequence[object]) -> dict | None:
    """Return the Status mapping of the newest task, or None without tasks."""
    task_items = [task for task in tasks if isinstance(task, dict)]
    if not task_items:
        return None
    latest = max(task_items, key=lambda task: str(task.get("CreatedAt", "")))
    status = latest.get("Status")
    return status if isinstance(status, dict) else {}


def workload_labels(workload: Any) -> dict[str, str]:
    """Return a Docker service's labels, or an empty mapping."""
    attrs = getattr(workload, "attrs", {}) or {}
    return attrs.get("Spec", {}).get("Labels") or {}


def _extract_latest_workload_state(
    tasks: list[object], no_tasks_state: str = "no_tasks"
) -> str:
    status = latest_task_status(tasks)
    if status is None:
        return no_tasks_state
    return str(status.get("State", "unknown")).strip().lower()


class AsyncDocker:
    def __init__(
        self,
        docker_config: DockerConfig | None = None,
        *,
        client: DockerClient | None = None,
    ) -> None:
        """Own the supplied client or create one from validated configuration."""
        config = docker_config or get_tactic_settings().config.docker

        try:
            self.client = (
                client if client is not None else DockerClient(base_url=config.base_url)
            )
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


async def get_workload_status_and_labels(
    async_docker: AsyncDocker, workload_id: str | None
) -> tuple[str, dict[str, str]]:
    """Return the newest task state and the labels of a RADAR Swarm service.

    States: "running" | task state | "no_tasks" | "not_found" | "no_container_id"
    | "unknown" | "error".
    """
    if not workload_id:
        return "no_container_id", {}
    try:
        docker_service = await async_docker.run(
            async_docker.client.services.get, workload_id
        )
        tasks = await async_docker.run(docker_service.tasks)
        labels = workload_labels(docker_service)
        return _extract_latest_workload_state(tasks), {
            str(key): str(value) for key, value in labels.items()
        }
    except docker.errors.NotFound:
        return "not_found", {}
    except Exception as exc:
        logger.debug("Error checking Docker status for %s: %s", workload_id, exc)
        return "error", {}


async def get_workload_docker_status(
    async_docker: AsyncDocker, workload_id: str | None
) -> str:
    """Return only the newest task state of a RADAR Swarm service."""
    return (await get_workload_status_and_labels(async_docker, workload_id))[0]
