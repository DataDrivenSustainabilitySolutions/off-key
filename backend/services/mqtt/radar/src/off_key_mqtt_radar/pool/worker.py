"""Lease RADAR workloads from the database and run each in a child process.

Each poll the worker, in order:

1. renews the lease of every child it still runs, including one that is
   stopping, so a lease never lapses while its child lives; a child whose row
   was asked to stop is ended in the background, and a child whose row is gone
   or no longer this worker's is killed at once;
2. records how each child that ended did so, and releases or finishes its row;
3. claims pending rows, and rows whose lease expired, up to its capacity.

A worker that cannot renew for half a lease kills every child, so no child
outlives the lease another worker may claim. A watchdog task checks this apart
from the poll, so a database call that hangs instead of failing still fences.
RADAR fences its own checkpoint writes as well, so a second copy of a monitor
cannot overwrite the first.
"""

import asyncio
import logging
import os
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from off_key_core.db.workloads import CRASH_HISTORY, OUTPUT_LIMIT
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

# Docker reports a SIGKILL as 137; the same code keeps crash records comparable.
SIGKILL_EXIT_CODE = 128 + signal.SIGKILL
MEMORY_HINT = "Killed by SIGKILL, usually for exceeding its memory limit"

# A preflight job constructs a pipeline and touches nothing else, so it gets
# only what a Python process needs: never the pool's database login or secrets.
PREFLIGHT_INHERITED = frozenset(
    {"PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR", "VIRTUAL_ENV", "ENVIRONMENT"}
)


def child_environment(kind: str, row_environment: dict) -> dict[str, str]:
    inherited = os.environ.items()
    if kind == "preflight":
        inherited = ((k, v) for k, v in inherited if k in PREFLIGHT_INHERITED)
    environment = dict(inherited)
    environment.update({str(k): str(v) for k, v in row_environment.items()})
    return environment


@dataclass(frozen=True)
class PoolOptions:
    worker_id: str
    runtime: str
    capacity: int
    poll_seconds: float
    lease_seconds: float
    stop_timeout_seconds: float
    restart_backoff_seconds: float
    max_restarts: int
    restart_window_seconds: float
    # A release runs a preflight-only replica of the target image before the
    # pool itself is replaced.
    kinds: tuple[str, ...] = ("monitor", "preflight")


@dataclass
class Child:
    """One running workload: its row and its process."""

    id: str
    kind: str
    restart: bool
    attempt: int
    memory_limit_bytes: int | None
    process: asyncio.subprocess.Process
    output: bytearray = field(default_factory=bytearray)
    reader: asyncio.Task | None = None
    killed_for_memory: bool = False
    # Set while the child is being ended on request; its row is finished then.
    stopping: asyncio.Task | None = None


def resident_bytes(pid: int) -> int | None:
    """Resident memory of a process, from /proc; None where unavailable."""
    try:
        with open(f"/proc/{pid}/status", encoding="ascii") as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        return None
    return None


def exit_code(returncode: int) -> int:
    """A signal death as a shell reports it (128 + signal), like Docker."""
    return 128 - returncode if returncode < 0 else returncode


_CLAIM = text("""
    WITH candidate AS (
        SELECT id, state AS previous_state, worker_id AS previous_worker
        FROM radar_workloads
        WHERE runtime = :runtime
          AND kind IN :kinds
          AND desired = 'run'
          AND (
              (state = 'pending' AND (not_before IS NULL OR not_before <= now()))
              OR (
                  state = 'running'
                  AND (lease_expires_at IS NULL OR lease_expires_at < now())
              )
          )
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT :limit
    )
    UPDATE radar_workloads AS w
    SET state = 'running',
        worker_id = :worker,
        lease_expires_at = now() + make_interval(secs => :lease),
        not_before = NULL,
        attempts = w.attempts + 1,
        exit_code = NULL,
        detail = NULL,
        output = NULL,
        updated_at = now()
    FROM candidate
    WHERE w.id = candidate.id
    RETURNING w.id, w.kind, w.module, w.environment, w.memory_limit_bytes,
              w.restart, w.attempts, candidate.previous_state,
              candidate.previous_worker
""").bindparams(bindparam("kinds", expanding=True))

_RENEW = text("""
    UPDATE radar_workloads
    SET lease_expires_at = now() + make_interval(secs => :lease), updated_at = now()
    WHERE worker_id = :worker AND id IN :ids
    RETURNING id, desired
""").bindparams(bindparam("ids", expanding=True))

_RELEASE = text("""
    UPDATE radar_workloads
    SET state = :state,
        worker_id = NULL,
        lease_expires_at = NULL,
        not_before = :not_before,
        exit_code = :exit_code,
        detail = :detail,
        output = :output,
        crashes = :crashes,
        updated_at = now()
    WHERE id = :id AND worker_id = :worker
""").bindparams(bindparam("crashes", type_=JSONB))

_CRASHES = text("SELECT crashes FROM radar_workloads WHERE id = :id")


class RadarPool:
    def __init__(
        self,
        engine: AsyncEngine,
        options: PoolOptions,
        stopping: Callable[[], bool],
        *,
        command: Callable[[str], list[str]] | None = None,
    ):
        self.engine = engine
        self.options = options
        self.stopping = stopping
        self.children: dict[str, Child] = {}
        self.command = command or (lambda module: [sys.executable, "-m", module])
        self.last_renewed = time.monotonic()
        self.healthy = False

    async def run_forever(self) -> None:
        logger.info(
            "event=radar_pool.started worker=%s runtime=%s capacity=%d",
            self.options.worker_id,
            self.options.runtime,
            self.options.capacity,
        )
        watchdog = asyncio.create_task(self.watch_lease())
        try:
            while not self.stopping():
                await self.tick()
                await asyncio.sleep(self.options.poll_seconds)
        finally:
            try:
                await self.drain()
            finally:
                watchdog.cancel()
            logger.info("event=radar_pool.stopped worker=%s", self.options.worker_id)

    async def watch_lease(self) -> None:
        """Fence even while a database call hangs instead of failing."""
        while True:
            await asyncio.sleep(self.options.poll_seconds / 2)
            if self.children and self.lease_at_risk():
                self.healthy = False
                self.kill_all()

    async def drain(self) -> None:
        """End every child and hand its row back, renewing while they end."""
        for child in self.children.values():
            self.stop(child, state="pending", detail="pool worker stopping")
        while self.children:
            try:
                await self.renew()
            except Exception:
                logger.exception("event=radar_pool.drain_renew_failed")
                if self.lease_at_risk():
                    self.kill_all()
                    return
            await asyncio.sleep(self.options.poll_seconds)

    def lease_at_risk(self) -> bool:
        return time.monotonic() - self.last_renewed > self.options.lease_seconds / 2

    def kill_all(self) -> None:
        """Fence: kill every child now; another worker may soon claim its row."""
        logger.error(
            "event=radar_pool.lease_lost worker=%s children=%d",
            self.options.worker_id,
            len(self.children),
        )
        for child in list(self.children.values()):
            self.discard(child)

    async def tick(self) -> None:
        try:
            await self.renew()
            await self.reap()
            await self.watch_memory()
            await self.claim()
            self.healthy = True
        except Exception:
            self.healthy = False
            logger.exception("event=radar_pool.tick_failed")
            if self.lease_at_risk():
                # Another worker may claim these rows once their leases expire.
                self.kill_all()

    async def renew(self) -> None:
        if not self.children:
            self.last_renewed = time.monotonic()
            return
        async with self.engine.begin() as connection:
            desired = dict(
                (
                    await connection.execute(
                        _RENEW,
                        {
                            "lease": self.options.lease_seconds,
                            "worker": self.options.worker_id,
                            "ids": list(self.children),
                        },
                    )
                ).all()
            )
        self.last_renewed = time.monotonic()
        for workload_id, child in list(self.children.items()):
            if workload_id not in desired:
                # Removed or taken over: the row is no longer this child's.
                logger.error("event=radar_pool.row_lost workload=%s", workload_id)
                self.discard(child)
            elif desired[workload_id] == "stop":
                self.stop(child, state="shutdown", detail="Stopped on request")

    def stop(self, child: Child, *, state: str, detail: str) -> None:
        """End a child in the background; its lease is renewed until it ends."""
        if child.stopping is not None:
            return

        async def end() -> None:
            await self.terminate(child)
            try:
                await self.finish(child, state=state, detail=detail, crash=False)
            except Exception:
                # Its lease lapses and another worker claims the row again.
                logger.exception(
                    "event=radar_pool.release_deferred workload=%s", child.id
                )
                self.children.pop(child.id, None)

        child.stopping = asyncio.create_task(end())

    def discard(self, child: Child) -> None:
        """Kill a child whose row this worker can no longer vouch for."""
        if child.process.returncode is None:
            child.process.kill()
        if child.stopping is not None:
            child.stopping.cancel()
        if child.reader is not None:
            child.reader.cancel()
        self.children.pop(child.id, None)

    async def reap(self) -> None:
        for child in list(self.children.values()):
            if child.process.returncode is None or child.stopping is not None:
                continue
            await self.collect_output(child)
            code = exit_code(child.process.returncode)
            if not child.restart:
                await self.finish(
                    child,
                    state="complete" if code == 0 else "failed",
                    exit_code=code,
                    crash=False,
                )
            elif code == 0:
                # A monitor that ends cleanly decided not to run (it was
                # stopped before it started); it is not restarted.
                await self.finish(child, state="complete", exit_code=code, crash=False)
            else:
                await self.finish(child, state="pending", exit_code=code, crash=True)

    async def watch_memory(self) -> None:
        for child in self.children.values():
            limit = child.memory_limit_bytes
            if not limit or child.process.returncode is not None:
                continue
            resident = resident_bytes(child.process.pid)
            if resident is not None and resident > limit:
                logger.warning(
                    "event=radar_pool.memory_limit workload=%s resident=%d limit=%d",
                    child.id,
                    resident,
                    limit,
                )
                child.killed_for_memory = True
                child.process.kill()

    async def claim(self) -> None:
        free = self.options.capacity - len(self.children)
        if free <= 0 or self.stopping():
            return
        async with self.engine.begin() as connection:
            rows = (
                await connection.execute(
                    _CLAIM,
                    {
                        "runtime": self.options.runtime,
                        "kinds": list(self.options.kinds),
                        "limit": free,
                        "worker": self.options.worker_id,
                        "lease": self.options.lease_seconds,
                    },
                )
            ).all()
        for row in rows:
            if row.previous_state == "running":
                logger.warning(
                    "event=radar_pool.lease_taken_over workload=%s previous=%s",
                    row.id,
                    row.previous_worker,
                )
            try:
                await self.start(row)
            except Exception as error:
                logger.exception("event=radar_pool.start_failed workload=%s", row.id)
                await self._release(
                    row.id,
                    state="failed",
                    detail=f"Could not start: {type(error).__name__}",
                )

    async def start(self, row) -> None:
        environment = child_environment(row.kind, row.environment)
        one_off = row.kind == "preflight"
        process = await asyncio.create_subprocess_exec(
            *self.command(row.module),
            env=environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE if one_off else None,
            # A child gets signals from this worker only, never the terminal's.
            start_new_session=True,
        )
        child = Child(
            id=row.id,
            kind=row.kind,
            restart=row.restart,
            attempt=row.attempts,
            memory_limit_bytes=row.memory_limit_bytes,
            process=process,
        )
        if one_off:
            child.reader = asyncio.create_task(self.read_output(child))
        self.children[row.id] = child
        logger.info(
            "event=radar_pool.child_started workload=%s kind=%s pid=%d attempt=%d",
            row.id,
            row.kind,
            process.pid,
            row.attempts,
        )

    @staticmethod
    async def read_output(child: Child) -> None:
        stream = child.process.stdout
        assert stream is not None
        while chunk := await stream.read(65536):
            child.output.extend(chunk)
            # Keep the end: a report is the last line a job prints.
            if len(child.output) > OUTPUT_LIMIT:
                del child.output[: len(child.output) - OUTPUT_LIMIT]

    @staticmethod
    async def collect_output(child: Child) -> None:
        if child.reader is not None:
            await child.reader

    async def terminate(self, child: Child) -> None:
        process = child.process
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(
                    process.wait(), self.options.stop_timeout_seconds
                )
            except TimeoutError:
                logger.warning("event=radar_pool.child_killed workload=%s", child.id)
                process.kill()
                await process.wait()
        await self.collect_output(child)

    async def finish(
        self,
        child: Child,
        *,
        state: str,
        crash: bool,
        exit_code: int | None = None,
        detail: str | None = None,
    ) -> None:
        crashes = None
        not_before = None
        hint = MEMORY_HINT if child.killed_for_memory else None
        if crash:
            now = datetime.now(UTC)
            async with self.engine.connect() as connection:
                previous = (
                    await connection.execute(_CRASHES, {"id": child.id})
                ).scalar_one_or_none() or []
            record = {
                "task_id": f"{child.id}:{child.attempt}",
                "state": "failed",
                "error": hint or f"exit code {exit_code}",
                "exit_code": exit_code,
                "ended_at": now.isoformat(),
                "node_id": self.options.worker_id,
            }
            if exit_code == SIGKILL_EXIT_CODE:
                record["hint"] = MEMORY_HINT
            crashes = [record, *previous][:CRASH_HISTORY]
            window = now - timedelta(seconds=self.options.restart_window_seconds)
            recent = sum(
                1
                for item in crashes
                if datetime.fromisoformat(str(item.get("ended_at"))) >= window
            )
            if recent >= self.options.max_restarts:
                state = "failed"
                detail = f"Crashed {recent} times; not restarted"
            else:
                delay = self.options.restart_backoff_seconds * 2 ** min(recent - 1, 6)
                not_before = now + timedelta(seconds=delay)
                detail = detail or hint or f"Crashed with exit code {exit_code}"
        output = None
        if child.output:
            output = child.output.decode("utf-8", errors="replace")
        await self._release(
            child.id,
            state=state,
            not_before=not_before,
            exit_code=exit_code,
            detail=detail,
            output=output,
            crashes=crashes,
        )
        self.children.pop(child.id, None)
        logger.info(
            "event=radar_pool.child_ended workload=%s state=%s exit_code=%s",
            child.id,
            state,
            exit_code,
        )

    async def _release(
        self,
        workload_id: str,
        *,
        state: str,
        not_before: datetime | None = None,
        exit_code: int | None = None,
        detail: str | None = None,
        output: str | None = None,
        crashes: list | None = None,
    ) -> None:
        async with self.engine.begin() as connection:
            if crashes is None:
                crashes = (
                    await connection.execute(_CRASHES, {"id": workload_id})
                ).scalar_one_or_none() or []
            await connection.execute(
                _RELEASE,
                {
                    "id": workload_id,
                    "worker": self.options.worker_id,
                    "state": state,
                    "not_before": not_before,
                    "exit_code": exit_code,
                    "detail": detail,
                    "output": output,
                    "crashes": crashes,
                },
            )
