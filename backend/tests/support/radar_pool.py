"""A real RADAR pool worker, in process, over a disposable database.

The pool claims, renews and releases rows exactly as a deployed replica does;
only the command its children run is a stand-in, so a test decides whether a
child sleeps, crashes, prints a report or grows past its memory limit.
"""

import asyncio
import sys
import textwrap
from contextlib import asynccontextmanager
from dataclasses import replace

from off_key_mqtt_radar.pool.worker import PoolOptions, RadarPool
from sqlalchemy.ext.asyncio import AsyncEngine

RUNTIME = "registry/radar@sha256:" + "a" * 64

SLEEP = "import time; time.sleep(120)"


def python(code: str) -> list[str]:
    return [sys.executable, "-c", textwrap.dedent(code)]


def options(**changes) -> PoolOptions:
    return replace(
        PoolOptions(
            worker_id="pool-test",
            runtime=RUNTIME,
            capacity=8,
            poll_seconds=0.05,
            lease_seconds=1.0,
            stop_timeout_seconds=2.0,
            restart_backoff_seconds=0.05,
            max_restarts=3,
            restart_window_seconds=60.0,
        ),
        **changes,
    )


@asynccontextmanager
async def running_pool(engine: AsyncEngine, *, code=SLEEP, **changes):
    """Run one pool worker until the block ends; children run ``code``.

    ``code`` is Python source, a mapping from a row's module to source, or None
    for the row's real module.
    """
    command = None
    if code is not None:

        def command(module: str) -> list[str]:
            return python(code[module] if isinstance(code, dict) else code)

    stopped = asyncio.Event()
    pool = RadarPool(engine, options(**changes), stopped.is_set, command=command)
    task = asyncio.create_task(pool.run_forever())
    try:
        yield pool
    finally:
        stopped.set()
        await asyncio.wait_for(task, 30)


async def eventually(check, *, within=15.0, interval=0.05):
    """Poll an async check until it returns a truthy value."""
    async with asyncio.timeout(within):
        while True:
            if result := await check():
                return result
            await asyncio.sleep(interval)
