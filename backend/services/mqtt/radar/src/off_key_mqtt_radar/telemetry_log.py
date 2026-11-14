"""Read a monitor's telemetry from the stored log, in commit order.

The collector appends every accepted reading to ``telemetry`` and takes each
row's ``log_seq`` under one lock until it commits, so positions commit in order:
once a reader has seen a position, no smaller one can still appear. A monitor
saves the position it has processed with its checkpoint, in the same
transaction as its evidence, and continues after it on restart. Nothing is
dropped for being slow; a reader that falls behind catches up.

Every reading carries the time the collector received it, and the monitor's
clocks follow that time while it works through the log, so a replayed backlog
is judged as it was live, the same way a Dojo replay is. Once caught up, the
clocks follow the wall clock, so a silent reading still goes stale.
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Iterable
from contextlib import suppress
from datetime import UTC
from typing import Any

from off_key_core.config.logs import logger
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .coverage import CoverageTracker
from .models import MQTTMessage

_READ = text("""
    SELECT log_seq, charger_id, type, timestamp, value
    FROM telemetry
    WHERE (charger_id, type) IN :streams AND log_seq > :position
    ORDER BY log_seq
    LIMIT :limit
""").bindparams(bindparam("streams", expanding=True))

_HEAD = text("""
    SELECT max(log_seq) FROM telemetry WHERE (charger_id, type) IN :streams
""").bindparams(bindparam("streams", expanding=True))


class LogClock:
    """The monitor's wall and receipt clock.

    While a monitor works through the log it reads the receipt time of the
    reading in hand, so a backlog is judged as it was live. Once it has caught
    up, the clock follows the wall clock, so silent readings still age. Once
    set it never runs backwards; before the first reading it reads the wall
    clock.
    """

    def __init__(self) -> None:
        self.now: float | None = None

    def advance(self, seconds: float) -> None:
        if self.now is None or seconds > self.now:
            self.now = seconds

    def __call__(self) -> float:
        return time.time() if self.now is None else self.now


def streams_from_topics(topics: Iterable[str]) -> list[tuple[str, str]]:
    """(charger_id, type) of each accepted topic ``telemetry/<entity>/<key>``."""
    streams = []
    for topic in topics:
        prefix, _, rest = topic.partition("/")
        entity, _, key = rest.partition("/")
        if prefix != "telemetry" or not entity or not key or {"+", "#"} & set(topic):
            raise ValueError(f"Not an accepted telemetry topic: {topic}")
        streams.append((entity, key))
    return sorted(set(streams))


class TelemetryLogReader:
    """Hand each new row of a monitor's streams to one handler, in order."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        topics: Iterable[str],
        *,
        clock: LogClock,
        coverage: CoverageTracker | None = None,
        poll_seconds: float = 0.5,
        batch_size: int = 500,
    ) -> None:
        self.session_factory = session_factory
        self.streams = streams_from_topics(topics)
        if not self.streams:
            raise ValueError("A monitor reads at least one telemetry stream")
        self.clock = clock
        self.coverage = coverage if coverage is not None else CoverageTracker()
        self.poll_seconds = poll_seconds
        self.batch_size = batch_size
        # The last position read and handed over; None before placing.
        self.cursor: int | None = None
        # The last position the monitor has processed. Its handler records it,
        # under the same lock its checkpoints take, so a checkpoint always
        # holds the position of exactly the readings its state contains.
        self.position: int | None = None
        self.handler: Callable[[MQTTMessage], Awaitable[None]] | None = None
        self.message_count = 0
        self.error_count = 0
        self.caught_up = False
        self.last_read_at: float | None = None
        self._failing_since: float | None = None
        self._shutdown = asyncio.Event()
        self._task: asyncio.Task | None = None

    def set_message_handler(
        self, handler: Callable[[MQTTMessage], Awaitable[None]]
    ) -> None:
        self.handler = handler

    async def place(self, position: int | None) -> None:
        """Continue after ``position``, or after the newest row when None."""
        if position is None:
            async with self.session_factory() as session:
                position = (await session.scalar(_HEAD, {"streams": self.streams})) or 0
        self.cursor = self.position = position

    async def start(self) -> None:
        """Read from the placed position until stopped."""
        if self.handler is None:
            raise RuntimeError("Set a message handler before reading the log")
        if self.cursor is None:
            raise RuntimeError("Place the reader before reading the log")
        self._shutdown.clear()
        self._task = asyncio.create_task(self._run())
        logger.info(
            "event=radar.log_reader_started streams=%d position=%d",
            len(self.streams),
            self.position,
        )

    async def stop(self) -> None:
        """Finish the row in hand, then stop; never interrupt a handler."""
        self._shutdown.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run(self) -> None:
        delay = self.poll_seconds
        while not self._shutdown.is_set():
            try:
                rows = await self._read()
            except Exception as error:
                self.error_count += 1
                if self._failing_since is None:
                    self._failing_since = time.monotonic()
                logger.warning("event=radar.log_read_failed error=%s", error)
                await self._pause(delay)
                delay = min(delay * 2, 30.0)
                continue
            self._failing_since = None
            delay = self.poll_seconds
            self.last_read_at = time.monotonic()
            for row in rows:
                if self._shutdown.is_set():
                    return
                await self._hand_over(row)
            self.caught_up = len(rows) < self.batch_size
            if self.caught_up:
                self.clock.advance(time.time())
                await self._pause(self.poll_seconds)

    async def _read(self) -> list[Any]:
        async with self.session_factory() as session:
            result = await session.execute(
                _READ,
                {
                    "streams": self.streams,
                    "position": self.cursor,
                    "limit": self.batch_size,
                },
            )
            return list(result.all())

    async def _hand_over(self, row: Any) -> None:
        received = row.timestamp.astimezone(UTC)
        self.clock.advance(received.timestamp())
        self.coverage.record_received()
        message = MQTTMessage(
            topic=f"telemetry/{row.charger_id}/{row.type}",
            payload=json.dumps(
                {"value": row.value, "timestamp": received.isoformat()}
            ).encode(),
            timestamp=received,
            received_monotonic=self.clock(),
            log_seq=row.log_seq,
        )
        await self.handler(message)
        self.cursor = row.log_seq
        self.message_count += 1

    def record_processed(self, log_seq: int) -> None:
        """The monitor's state now includes the reading at ``log_seq``."""
        self.position = log_seq

    async def _pause(self, seconds: float) -> None:
        with suppress(TimeoutError):
            await asyncio.wait_for(self._shutdown.wait(), seconds)

    def get_health_status(self) -> dict[str, Any]:
        coverage = self.coverage.snapshot_json()
        status, reason = "healthy", "ok"
        if self._failing_since is not None:
            status, reason = "unhealthy", "log_unavailable"
        elif coverage["has_gaps"]:
            status, reason = "degraded", "coverage_gap"
        return {
            "status": status,
            "reason": reason,
            "position": self.position,
            "cursor": self.cursor,
            "caught_up": self.caught_up,
            "message_count": self.message_count,
            "error_count": self.error_count,
            "coverage": coverage,
        }
