import asyncio
import time
from collections.abc import Callable
from typing import Any

import docker
from docker import DockerClient
from off_key_core.config.logs import log_performance, logger

from ..config.config import DockerConfig, get_tactic_settings


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


async def get_workload_docker_status(
    async_docker: AsyncDocker, container_id: str
) -> str:
    """Return the latest task state of a RADAR Swarm service by ID.

    Returns:
        "running" | task state | "no_tasks" | "not_found" | "no_container_id"
        | "unknown" | "error"
    """
    if not container_id:
        return "no_container_id"
    try:
        docker_service = await async_docker.run(
            async_docker.client.services.get, container_id
        )
        tasks = await async_docker.run(docker_service.tasks)
        return _extract_latest_workload_state(tasks)
    except docker.errors.NotFound:
        return "not_found"
    except Exception as exc:
        logger.debug("Error checking Docker status for %s: %s", container_id, exc)
        return "error"
