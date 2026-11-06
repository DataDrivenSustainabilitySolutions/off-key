"""Bulk status probes leave Docker slots free for workload changes."""

import asyncio
import threading
from unittest.mock import MagicMock

from off_key_tactic_middleware.config.config import DockerConfig
from off_key_tactic_middleware.facades.docker import AsyncDocker


async def test_probes_use_at_most_half_of_the_docker_slots():
    docker = AsyncDocker(DockerConfig(max_concurrent_calls=4), client=MagicMock())
    release = threading.Event()
    both_running = threading.Event()
    running = 0
    peak = 0
    lock = threading.Lock()

    def slow_probe():
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
            if running == 2:
                both_running.set()
        release.wait(5)
        with lock:
            running -= 1

    probes = [asyncio.create_task(docker.run_probe(slow_probe)) for _ in range(6)]
    assert await asyncio.to_thread(both_running.wait, 5)

    # A workload change still gets a slot while probes are waiting.
    assert await asyncio.wait_for(docker.run(lambda: "created"), 2) == "created"

    release.set()
    await asyncio.gather(*probes)
    assert peak == 2
