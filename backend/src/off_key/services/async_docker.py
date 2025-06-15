import os
import asyncio

from docker import DockerClient
from typing import Callable, Any

MAX_CONCURRENT_CALLS = int(os.getenv('DOCKER_MAX_CONCURRENT_CALLS'))

class AsyncDocker:
    def __init__(self, max_concurrent_calls: int = MAX_CONCURRENT_CALLS):
        self.client = DockerClient(base_url=f'{os.getenv('DOCKER_API_URL')}:{os.getenv('DOCKER_API_PORT')}')
        self.semaphore = asyncio.Semaphore(max_concurrent_calls)

    async def run(self, func: Callable, *args, **kwargs) -> Any:
        async with self.semaphore:
            return await asyncio.to_thread(func, *args, **kwargs)
