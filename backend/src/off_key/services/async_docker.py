import os
import asyncio

from docker import DockerClient, tls
from typing import Callable, Any

MAX_CONCURRENT_CALLS = int(os.getenv('DOCKER_MAX_CONCURRENT_CALLS'))

class AsyncDocker:
    def __init__(self, max_concurrent_calls: int = MAX_CONCURRENT_CALLS):
        tls_config = tls.TLSConfig(
            client_cert=('/etc/docker/client-cert.pem', '/etc/docker/client-key.pem'),
            ca_cert='/etc/docker/ca.pem',
            verify=True,
        )
        self.client = DockerClient(base_url=f'https://{os.getenv('MANAGER_NODE_IP')}:2376', tls=tls_config)
        self.semaphore = asyncio.Semaphore(max_concurrent_calls)

    async def run(self, func: Callable, *args, **kwargs) -> Any:
        async with self.semaphore:
            return await asyncio.to_thread(func, *args, **kwargs)
