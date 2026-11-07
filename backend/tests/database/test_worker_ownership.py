"""Takeover cannot pass an in-flight effect or admit a retired worker."""

import pytest
from off_key_core.db.worker_ownership import WorkerOwnership, WorkerOwnershipLost
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_lost_owner_cannot_write_and_takeover_waits_for_inflight_effect(
    disposable_database,
):
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    try:
        async with (
            engine.connect() as owner,
            engine.connect() as effect,
            engine.connect() as replacement,
        ):
            lease = await WorkerOwnership.acquire(owner, 73128001)
            assert lease is not None
            assert await WorkerOwnership.acquire(replacement, lease.key) is None
            await replacement.rollback()
            await lease.fence(effect)
            assert await replacement.scalar(
                text("SELECT pg_terminate_backend(:pid)"), {"pid": lease.pid}
            )
            await replacement.commit()
            await owner.invalidate()
            # The shared effect lock outlives the dead owner's connection.
            assert await WorkerOwnership.acquire(replacement, lease.key) is None
            await replacement.rollback()
            await effect.commit()
            next_lease = await WorkerOwnership.acquire(replacement, lease.key)
            assert next_lease is not None
            with pytest.raises(WorkerOwnershipLost):
                await lease.fence(effect)
            await effect.rollback()
            await next_lease.fence(effect)
            await effect.commit()
            await next_lease.release(replacement)
    finally:
        await engine.dispose()
