"""Worker entry points stop every task once the first one ends."""

import asyncio

import pytest
from off_key_core.utils.tasks import run_until_first_exit


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, RuntimeError("health API crashed")])
async def test_first_exit_cancels_the_rest_and_propagates_its_error(failure):
    async def first():
        if failure is not None:
            raise failure

    blocker = asyncio.create_task(asyncio.Event().wait())
    tasks = {asyncio.create_task(first()), blocker}

    if failure is None:
        await run_until_first_exit(tasks)
    else:
        with pytest.raises(RuntimeError, match="health API crashed"):
            await run_until_first_exit(tasks)

    assert blocker.cancelled()
