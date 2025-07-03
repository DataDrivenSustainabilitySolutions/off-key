import os
import asyncio

from docker import DockerClient
from typing import Callable, Any

MAX_CONCURRENT_CALLS = int(os.getenv("DOCKER_MAX_CONCURRENT_CALLS", "5"))


class AsyncDocker:
    def __init__(self, max_concurrent_calls: int = MAX_CONCURRENT_CALLS):
        docker_url = os.getenv("DOCKER_API_URL", "http://socket-proxy")
        docker_port = os.getenv("DOCKER_API_PORT", "2375")
        self.client = DockerClient(base_url=f"{docker_url}:{docker_port}")
        self.semaphore = asyncio.Semaphore(max_concurrent_calls)

    async def run(self, func: Callable, *args, **kwargs) -> Any:
        async with self.semaphore:
            return await asyncio.to_thread(func, *args, **kwargs)
