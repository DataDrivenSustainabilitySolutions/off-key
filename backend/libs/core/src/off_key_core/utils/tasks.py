"""Run a worker's long-lived tasks until the first one ends."""

import asyncio
from contextlib import suppress


async def run_until_first_exit(tasks: set[asyncio.Task]) -> None:
    """Wait for the first task to finish, re-raise its error, cancel the rest."""
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        pending = [task for task in tasks if not task.done()]
        for task in pending:
            task.cancel()
        for task in pending:
            with suppress(asyncio.CancelledError):
                await task
