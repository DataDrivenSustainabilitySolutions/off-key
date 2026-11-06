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
from dataclasses import dataclass, field
from datetime import datetime

from off_key_core.schemas.dojo import RunAlignment
from off_key_core.schemas.pipelines import PipelineExecutionConfig
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ..execution_errors import FatalExecutionError
from .replay import Replay, ReplayResult, detection_config

logger = logging.getLogger(__name__)

RESULT_COLUMNS = ("run_id", "sequence", "timestamp", "phase", "score", "threshold")
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
FINISH = text(
    "UPDATE dojo_runs SET status = :status, error = :error, finished_at = now(), "
    "heartbeat_at = now(), points_read = :points_read, "
    "result_count = :result_count, alarm_count = :alarm_count, "
    "stats = CAST(:stats AS jsonb) "
    "WHERE id = :id AND worker = :worker AND status = 'running'"
)
RELEASE = text(
    "UPDATE dojo_runs SET status = 'queued', worker = NULL, started_at = NULL, "
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


class RunStopped(Exception):
    """The run ended outside this worker: cancelled, deleted or taken over."""


@dataclass
class _Run:
    id: str
    points_read: int = 0
    pending: list[ReplayResult] = field(default_factory=list)
    replay: Replay | None = None

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
            if run.replay is not None:
                run.replay.close()
        logger.info(
            "event=dojo.run_finished run_id=%s points=%s results=%s",
            run_id,
            run.points_read,
            run.replay.sequence if run.replay else 0,
        )

    async def _replay(self, run: _Run, config: dict) -> None:
        execution = PipelineExecutionConfig.model_validate(config["execution"])
        alignment = RunAlignment.model_validate(config["alignment"])
        run.replay = Replay(
            detection_config(execution, alignment, self.options.memory_limit_mb)
        )
        beat = time.monotonic()
        async for topic, stamp, value in merged_points(
            self.engine, config["series"], self.options.read_batch
        ):
            if self.should_stop():
                raise _Interrupted
            run.points_read += 1
            result = run.replay.step(topic, stamp, value)
            if result is not None:
                run.pending.append(result)
            if (
                len(run.pending) >= self.options.write_batch
                or time.monotonic() - beat >= self.options.heartbeat_seconds
            ):
                if await self._flush(run):
                    await self._finish(run, "cancelled", None)
                    return
                beat = time.monotonic()
        await self._finish(run, "succeeded", None)

    async def _write(self, connection, run: _Run) -> None:
        if not run.pending:
            return
        raw = await connection.get_raw_connection()
        await raw.driver_connection.copy_records_to_table(
            "dojo_run_results",
            records=[
                (
                    run.id,
                    item.sequence,
                    item.timestamp,
                    item.phase,
                    item.score,
                    item.threshold,
                    item.alarm,
                )
                for item in run.pending
            ],
            columns=[*RESULT_COLUMNS, "alarm"],
        )
        run.pending.clear()

    async def _flush(self, run: _Run) -> bool:
        """Store pending results and refresh the heartbeat; True if cancelled."""
        async with self.engine.begin() as connection:
            row = (
                await connection.execute(PROGRESS, run.progress(self.options.worker_id))
            ).first()
            if row is None:
                raise RunStopped
            await self._write(connection, run)
        return bool(row.cancel_requested)

    async def _finish(self, run: _Run, status: str, error: str | None) -> None:
        # Results before a failure stay, so the run shows how far it came.
        async with self.engine.begin() as connection:
            outcome = await connection.execute(
                FINISH,
                {
                    **run.progress(self.options.worker_id),
                    "status": status,
                    "error": error,
                },
            )
            if outcome.rowcount:
                await self._write(connection, run)

    async def _release(self, run: _Run) -> None:
        async with self.engine.begin() as connection:
            outcome = await connection.execute(
                RELEASE, {"id": run.id, "worker": self.options.worker_id}
            )
            if outcome.rowcount:
                await connection.execute(DELETE_RESULTS, {"id": run.id})


class _Interrupted(Exception):
    """The worker is shutting down mid-run."""


def _bounded(message: str, limit: int = 2000) -> str:
    return message if len(message) <= limit else message[: limit - 1] + "…"
