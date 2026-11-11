"""The Dojo worker: claim queued runs and replay them one at a time.

Each replica runs one replay, so the number of replicas is the number of runs
that execute at once. A run is claimed with ``FOR UPDATE SKIP LOCKED``; the
worker refreshes its heartbeat while it runs, and a run whose heartbeat
stopped is failed by whichever worker polls next. A worker that is asked to
stop puts its run back in the queue and drops the partial results.
"""

import asyncio
import heapq
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime

from off_key_core.db.models import DojoRunResult
from off_key_core.schemas.dojo import RunAlignment
from off_key_core.schemas.pipelines import PipelineExecutionConfig
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ..execution_errors import FatalExecutionError
from .replay import Replay, ReplayResult, detection_config

logger = logging.getLogger(__name__)

STALE_ERROR = "The Dojo worker stopped during the run"

FAIL_STALE = text(
    "UPDATE dojo_runs SET status = 'failed', error = :error, finished_at = now() "
    "WHERE status = 'running' "
    "AND heartbeat_at < now() - make_interval(secs => :stale)"
)
CLAIM = text(
    "UPDATE dojo_runs SET status = 'running', worker = :worker, "
    "started_at = now(), heartbeat_at = now() "
    "WHERE id = (SELECT id FROM dojo_runs WHERE status = 'queued' "
    "ORDER BY created_at, id FOR UPDATE SKIP LOCKED LIMIT 1) "
    "RETURNING id, config"
)
PROGRESS = text(
    "UPDATE dojo_runs SET heartbeat_at = now(), points_read = :points_read, "
    "result_count = :result_count, alarm_count = :alarm_count, "
    "stats = CAST(:stats AS jsonb) "
    "WHERE id = :id AND worker = :worker AND status = 'running' "
    "RETURNING cancel_requested"
)
HEARTBEAT = text(
    "UPDATE dojo_runs SET heartbeat_at = clock_timestamp() "
    "WHERE id = :id AND worker = :worker AND status = 'running' "
    "RETURNING cancel_requested"
)
FINISH = text(
    "UPDATE dojo_runs SET status = CASE WHEN cancel_requested THEN 'cancelled' "
    "ELSE :status END, error = CASE WHEN cancel_requested THEN NULL ELSE :error END, "
    "finished_at = now(), "
    "heartbeat_at = now(), points_read = :points_read, "
    "result_count = :result_count, alarm_count = :alarm_count, "
    "stats = CAST(:stats AS jsonb), "
    # The one thing a worker adds to a run's settings: which of the compared
    # calibration methods failed on its scores, and why.
    "config = CASE WHEN CAST(:failed AS jsonb) IS NULL THEN config ELSE "
    "jsonb_set(config, '{calibration_comparison,failed}', CAST(:failed AS jsonb)) "
    "END "
    "WHERE id = :id AND worker = :worker AND status = 'running'"
)
RELEASE = text(
    "UPDATE dojo_runs SET status = CASE WHEN cancel_requested THEN 'cancelled' "
    "ELSE 'queued' END, finished_at = CASE WHEN cancel_requested THEN now() "
    "ELSE NULL END, worker = NULL, started_at = NULL, "
    "heartbeat_at = NULL, points_read = 0, result_count = 0, alarm_count = 0, "
    "stats = '{}'::jsonb "
    "WHERE id = :id AND worker = :worker AND status = 'running'"
)
DELETE_RESULTS = text("DELETE FROM dojo_run_results WHERE run_id = :id")
SERIES_PAGE = text(
    "SELECT timestamp, value FROM dojo_dataset_points "
    "WHERE series_id = :series AND (CAST(:after AS timestamptz) IS NULL "
    "OR timestamp > CAST(:after AS timestamptz)) "
    "ORDER BY timestamp LIMIT :limit"
)


@dataclass
class WorkerOptions:
    worker_id: str
    memory_limit_mb: int = 1024
    read_batch: int = 20_000
    write_batch: int = 5_000
    heartbeat_seconds: float = 10.0
    stale_seconds: float = 120.0
    poll_seconds: float = 2.0

    def __post_init__(self) -> None:
        if not 0 < self.heartbeat_seconds < self.stale_seconds:
            raise ValueError(
                "Heartbeat interval must be positive and below stale timeout"
            )
        if self.read_batch < 1 or self.write_batch < 1:
            raise ValueError("Read and write batches must be positive")


class RunStopped(Exception):
    """The run ended outside this worker: cancelled, deleted or taken over."""


@dataclass
class _Run:
    id: str
    points_read: int = 0
    pending: list[ReplayResult] = field(default_factory=list)
    replay: Replay | None = None
    mutations: asyncio.Lock = field(default_factory=asyncio.Lock)
    cancel_requested: bool = False
    heartbeat_error: Exception | None = None

    def progress(self, worker: str) -> dict:
        replay = self.replay
        return {
            "id": self.id,
            "worker": worker,
            "points_read": self.points_read,
            "result_count": replay.sequence if replay else 0,
            "alarm_count": replay.alarm_count if replay else 0,
            "stats": _json(replay.stats() if replay else {}),
        }

    def failed_methods(self) -> str | None:
        comparison = self.replay.comparison if self.replay else None
        return _json(comparison.failed) if comparison and comparison.failed else None


def _json(value) -> str:
    return json.dumps(value, separators=(",", ":"))


async def merged_points(
    engine: AsyncEngine, series: list[dict], batch: int
) -> AsyncIterator[tuple[str, float, float]]:
    """Every point of the bound series, in time order; ties by series order."""

    async def page(series_id: str, after: datetime | None):
        async with engine.connect() as connection:
            rows = await connection.execute(
                SERIES_PAGE, {"series": series_id, "after": after, "limit": batch}
            )
            return rows.all()

    cursors: list[tuple[float, int, int]] = []
    pages: dict[int, list] = {}
    for order, item in enumerate(series):
        pages[order] = await page(item["id"], None)
        if pages[order]:
            cursors.append((pages[order][0][0].timestamp(), order, 0))
    heapq.heapify(cursors)
    while cursors:
        stamp, order, index = heapq.heappop(cursors)
        rows = pages[order]
        yield series[order]["topic"], stamp, float(rows[index][1])
        index += 1
        if index == len(rows):
            if len(rows) < batch:
                continue
            rows = pages[order] = await page(series[order]["id"], rows[-1][0])
            index = 0
            if not rows:
                continue
        heapq.heappush(cursors, (rows[index][0].timestamp(), order, index))


class DojoWorker:
    def __init__(
        self,
        engine: AsyncEngine,
        options: WorkerOptions,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        self.engine = engine
        self.options = options
        self.should_stop = should_stop

    async def run_forever(self) -> None:
        logger.info("event=dojo.worker_started worker=%s", self.options.worker_id)
        while not self.should_stop():
            if not await self.run_once():
                await asyncio.sleep(self.options.poll_seconds)
        logger.info("event=dojo.worker_stopped worker=%s", self.options.worker_id)

    async def run_once(self) -> bool:
        """Claim and execute one queued run; False when the queue is empty."""
        async with self.engine.begin() as connection:
            await connection.execute(
                FAIL_STALE,
                {"error": STALE_ERROR, "stale": self.options.stale_seconds},
            )
            claimed = (
                await connection.execute(CLAIM, {"worker": self.options.worker_id})
            ).first()
        if claimed is None:
            return False
        await self.execute(claimed.id, claimed.config)
        return True

    async def execute(self, run_id: str, config: dict) -> None:
        run = _Run(run_id)
        finished = asyncio.Event()
        heartbeat = asyncio.create_task(self._keep_alive(run, finished))
        logger.info("event=dojo.run_started run_id=%s", run_id)
        try:
            await self._replay(run, config)
        except RunStopped:
            logger.info("event=dojo.run_stopped_elsewhere run_id=%s", run_id)
            return
        except _Interrupted:
            await self._release(run)
            logger.info("event=dojo.run_requeued run_id=%s", run_id)
            return
        except (FatalExecutionError, ValidationError, ValueError) as error:
            await self._finish(run, "failed", _bounded(str(error)))
            logger.info("event=dojo.run_failed run_id=%s error=%s", run_id, error)
            return
        except Exception as error:
            logger.exception("event=dojo.run_crashed run_id=%s", run_id)
            await self._finish(
                run, "failed", _bounded(f"{type(error).__name__}: {error}")
            )
            return
        finally:
            finished.set()
            await heartbeat
            if run.replay is not None:
                await asyncio.to_thread(run.replay.close)
        logger.info(
            "event=dojo.run_finished run_id=%s points=%s results=%s",
            run_id,
            run.points_read,
            run.replay.sequence if run.replay else 0,
        )

    async def _replay(self, run: _Run, config: dict) -> None:
        execution = PipelineExecutionConfig.model_validate(config["execution"])
        alignment = RunAlignment.model_validate(config["alignment"])

        def initialize():
            # Install the resource in the worker thread so cancellation while
            # joining that thread still leaves it visible to execute's cleanup.
            run.replay = Replay(
                detection_config(execution, alignment, self.options.memory_limit_mb),
                config.get("calibration_comparison"),
            )

        await _compute(initialize)
        beat = time.monotonic()
        points = merged_points(self.engine, config["series"], self.options.read_batch)
        async for batch in _batches(points):
            # Fitting and scoring must not block the independent heartbeat.
            await _compute(self._advance, run, batch)
            if run.heartbeat_error is not None:
                raise run.heartbeat_error
            if run.cancel_requested:
                await self._finish(run, "cancelled", None)
                return
            if (
                len(run.pending) >= self.options.write_batch
                or time.monotonic() - beat >= self.options.heartbeat_seconds
            ):
                if await self._flush(run):
                    await self._finish(run, "cancelled", None)
                    return
                beat = time.monotonic()
        await self._finish(run, "succeeded", None)

    def _advance(self, run: _Run, batch: list[tuple[str, float, float]]) -> None:
        assert run.replay is not None
        for topic, stamp, value in batch:
            if self.should_stop():
                raise _Interrupted
            if run.cancel_requested or run.heartbeat_error is not None:
                return
            run.points_read += 1
            result = run.replay.step(topic, stamp, value)
            if result is not None:
                run.pending.append(result)

    async def _keep_alive(self, run: _Run, finished: asyncio.Event) -> None:
        try:
            while not finished.is_set():
                # Our own result transaction locks the run too. Wait outside
                # the heartbeat timeout so a slow commit is not mistaken for
                # a dead worker; flush refreshes its heartbeat before commit.
                async with (
                    run.mutations,
                    asyncio.timeout(self.options.heartbeat_seconds),
                ):
                    async with self.engine.begin() as connection:
                        row = (
                            await connection.execute(
                                HEARTBEAT,
                                {"id": run.id, "worker": self.options.worker_id},
                            )
                        ).first()
                    if row is None:
                        raise RunStopped
                    run.cancel_requested = bool(row.cancel_requested)
                with suppress(TimeoutError):
                    await asyncio.wait_for(
                        finished.wait(), self.options.heartbeat_seconds
                    )
        except Exception as error:
            run.heartbeat_error = error

    async def _write(self, connection, run: _Run) -> int:
        if not run.pending:
            return 0
        records = [
            dict(
                run_id=run.id,
                sequence=item.sequence,
                timestamp=item.timestamp,
                phase=item.phase,
                score=item.score,
                threshold=item.threshold,
                alarm=item.alarm,
                method_alarms=item.method_alarms,
            )
            for item in run.pending
        ]
        # A connection can fail after the server commits. Retrying the same
        # numbered results must not duplicate them or prevent saving the rest.
        await connection.execute(
            insert(DojoRunResult).on_conflict_do_nothing(
                index_elements=["run_id", "sequence"]
            ),
            records,
        )
        return len(records)

    async def _flush(self, run: _Run) -> bool:
        """Store pending results and refresh the heartbeat; True if cancelled."""
        async with run.mutations, self.engine.begin() as connection:
            row = (
                await connection.execute(PROGRESS, run.progress(self.options.worker_id))
            ).first()
            if row is None:
                raise RunStopped
            written = await self._write(connection, run)
            row = (
                await connection.execute(
                    HEARTBEAT, {"id": run.id, "worker": self.options.worker_id}
                )
            ).first()
        del run.pending[:written]
        return bool(row.cancel_requested)

    async def _finish(self, run: _Run, status: str, error: str | None) -> None:
        # Results before a failure stay, so the run shows how far it came.
        written = 0
        async with run.mutations, self.engine.begin() as connection:
            outcome = await connection.execute(
                FINISH,
                {
                    **run.progress(self.options.worker_id),
                    "status": status,
                    "error": error,
                    "failed": run.failed_methods(),
                },
            )
            if outcome.rowcount:
                written = await self._write(connection, run)
        del run.pending[:written]

    async def _release(self, run: _Run) -> None:
        async with run.mutations, self.engine.begin() as connection:
            outcome = await connection.execute(
                RELEASE, {"id": run.id, "worker": self.options.worker_id}
            )
            if outcome.rowcount:
                await connection.execute(DELETE_RESULTS, {"id": run.id})


class _Interrupted(Exception):
    """The worker is shutting down mid-run."""


async def _batches(points, size: int = 256):
    batch = []
    async for point in points:
        batch.append(point)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


async def _compute(function, *args):
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A running thread cannot be cancelled. Join it before closing its
        # detector or relinquishing this run to another worker.
        await task
        raise


def _bounded(message: str, limit: int = 2000) -> str:
    return message if len(message) <= limit else message[: limit - 1] + "…"
