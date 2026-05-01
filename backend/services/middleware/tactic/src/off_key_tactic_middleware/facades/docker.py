import asyncio
import time

import docker.errors
from docker import DockerClient
from typing import Callable, Any
from off_key_core.config.logs import logger, log_performance
from ..config.config import get_tactic_settings


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
                f" URL: {config.base_url} | Error: {str(e)}"
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
            logger.error(f"Docker operation failed: {func_name} | Error: {str(e)}")
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
    """Return the running status of a Docker workload by ID.

    Tries Swarm services first (reads task state), then falls back to plain
    containers (reads container status). Both callers — RadarOrchestrationService
    and RadarStatusReconciliationService — delegate here to avoid duplicating the
    service→container probe-and-fallback logic.

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
            if tasks:
                latest = max(tasks, key=lambda t: t.get("CreatedAt", ""))
                return latest.get("Status", {}).get("State", "unknown")
            return "no_tasks"
        except docker.errors.NotFound:
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
