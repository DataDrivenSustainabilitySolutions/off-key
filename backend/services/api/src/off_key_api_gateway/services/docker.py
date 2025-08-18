import os
import asyncio
import time

from docker import DockerClient
from typing import Callable, Any
from off_key_core.config.logs import logger, log_performance

MAX_CONCURRENT_CALLS = int(os.getenv("DOCKER_MAX_CONCURRENT_CALLS", "5"))


class AsyncDocker:
    def __init__(self, max_concurrent_calls: int = MAX_CONCURRENT_CALLS):
        docker_url = os.getenv("DOCKER_API_URL", "http://socket-proxy")
        docker_port = os.getenv("DOCKER_API_PORT", "2375")
        base_url = f"{docker_url}:{docker_port}"

        try:
            self.client = DockerClient(base_url=base_url)
            self.semaphore = asyncio.Semaphore(max_concurrent_calls)
            logger.info(
                f"Docker client initialized successfully |"
                f" URL: {base_url} | Max concurrent: {max_concurrent_calls}"
            )
        except Exception as e:
            logger.error(
                f"Failed to initialize Docker client |"
                f" URL: {base_url} | Error: {str(e)}"
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
