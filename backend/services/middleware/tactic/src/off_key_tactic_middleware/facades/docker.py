import asyncio
import time

from docker import DockerClient
from typing import Callable, Any
from off_key_core.config.logs import logger, log_performance
from off_key_tactic_middleware.config import tactic_settings


class AsyncDocker:
    def __init__(self, docker_config=None):
        config = docker_config or tactic_settings.config.docker

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
