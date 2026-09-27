"""Bounded recent-rate measurements for collection, independent of UI polling."""

import time
from collections import deque
from datetime import datetime

from .collection_buffer import CollectionBuffer
from .telemetry import DatabaseWriter
from .telemetry_models import WriteStatus


class CollectionDiagnostics:
    def __init__(self, buffer: CollectionBuffer, writer: DatabaseWriter):
        self.buffer = buffer
        self.writer = writer
        self.last_state_write_at: datetime | None = None
        self._samples: deque[tuple[float, dict[str, int]]] = deque(maxlen=32)

    def snapshot(self, *, connected: bool) -> dict:
        now = time.monotonic()
        counters = self.buffer.metrics()
        totals = {
            key: counters.get(key, 0)
            for key in ("received", "accepted", "invalid", "overload_dropped")
        }
        totals["written"] = self.writer.total_records_written
        # At most one sample per second; keep an anchor for the last 30 seconds.
        if not self._samples or now - self._samples[-1][0] >= 1:
            self._samples.append((now, totals))
        while len(self._samples) > 2 and self._samples[1][0] <= now - 30:
            self._samples.popleft()
        start, baseline = self._samples[0]
        elapsed = now - start
        rates = {
            key: round(max(0, value - baseline[key]) / elapsed, 2)
            if elapsed >= 1
            else None
            for key, value in totals.items()
        }
        writes = [
            timestamp
            for timestamp in (
                self.last_state_write_at,
                self.writer.last_successful_write_at,
            )
            if timestamp is not None
        ]
        batches = list(self.writer.processing_batches.values())
        return {
            "mqtt_connected": connected,
            "window_seconds": round(elapsed, 1),
            "rates": rates,
            "last_received_at": self.buffer.last_received_at.isoformat()
            if self.buffer.last_received_at
            else None,
            "last_database_write_at": max(writes).isoformat() if writes else None,
            "original_queue": counters["original_queue"],
            "original_capacity": counters["original_capacity"],
            "sample_slots": counters["sample_slots"],
            "database_queue": self.writer.pending_batch.size()
            + sum(batch.size() for batch in batches),
            "database_capacity": 2 * self.writer.batch_size,
            "database_retrying": any(
                batch.status in {WriteStatus.RETRYING, WriteStatus.FAILED}
                for batch in batches
            ),
        }
