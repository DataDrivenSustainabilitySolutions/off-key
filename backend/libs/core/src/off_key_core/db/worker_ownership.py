"""Fence worker effects with the same advisory lock used for takeover.

A leader takes the exclusive lock, downgrades to a session shared lock, and
keeps that connection. Each effect transaction takes a shared lock and checks
the original leader. Takeover requires the exclusive lock, so it cannot pass
an in-flight effect; after takeover an old writer fails the identity check.
"""

from dataclasses import dataclass

from sqlalchemy import text


class WorkerOwnershipLost(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerOwnership:
    key: int
    pid: int

    @classmethod
    async def acquire(cls, connection, key: int):
        if not await connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
        ):
            return None
        try:
            pid = await connection.scalar(text("SELECT pg_backend_pid()"))
            # The exclusive lock protects the downgrade; no second leader can
            # acquire between releasing exclusive ownership and retaining shared.
            await connection.execute(
                text("SELECT pg_advisory_lock_shared(:key)"), {"key": key}
            )
            await connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": key}
            )
            await connection.commit()
        except BaseException:
            # Session locks survive rollback. Never return a partly acquired
            # ownership connection to the pool.
            await connection.invalidate()
            raise
        return cls(key, pid)

    async def fence(self, session) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": self.key}
        )
        alive = await session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' "
                "AND pid = :pid AND classid = 0 AND objid = :key AND objsubid = 1 "
                "AND mode = 'ShareLock' AND granted AND database = "
                "(SELECT oid FROM pg_database WHERE datname = current_database()))"
            ),
            {"pid": self.pid, "key": self.key},
        )
        if not alive:
            raise WorkerOwnershipLost("This worker no longer owns collection")

    async def release(self, connection) -> None:
        await connection.execute(
            text("SELECT pg_advisory_unlock_shared(:key)"), {"key": self.key}
        )
        await connection.commit()
