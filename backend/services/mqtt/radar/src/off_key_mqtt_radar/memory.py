"""Process-memory monitoring for the RADAR service."""

import gc
import logging
import os
import time
from collections.abc import Callable
from functools import cache

import psutil


@cache
def _current_process() -> psutil.Process:
    return psutil.Process(os.getpid())


def process_rss_mb() -> float:
    """Resident memory of this process, or 0.0 when the OS refuses the read."""
    try:
        return _current_process().memory_info().rss / 1024 / 1024
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return 0.0


# A process rarely hands memory back to the system, so it can stay above the
# threshold after collecting. A full collection costs time in proportion to the
# heap, so above the threshold it runs at most this often, not on every reading.
CLEANUP_INTERVAL_SECONDS = 30.0


class MemoryManager:
    """Monitor process memory and trigger explicit garbage collection."""

    def __init__(
        self,
        max_memory_mb: float = 2000,
        cleanup_threshold: float = 0.8,
        interval_seconds: float = CLEANUP_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_memory_mb = max_memory_mb
        self.cleanup_threshold = cleanup_threshold
        self.interval_seconds = interval_seconds
        self.clock = clock
        self._last_cleanup: float | None = None
        self.process = psutil.Process(os.getpid())
        self.logger = logging.getLogger(__name__)

    def get_memory_usage(self) -> float:
        return self.process.memory_info().rss / 1024 / 1024

    def should_cleanup(self) -> bool:
        """Whether memory is above the threshold and no collection ran just now."""
        last = self._last_cleanup
        if last is not None and self.clock() - last < self.interval_seconds:
            return False
        return self.get_memory_usage() > self.max_memory_mb * self.cleanup_threshold

    def force_cleanup(self) -> float:
        self._last_cleanup = self.clock()
        before_memory = self.get_memory_usage()
        collected = gc.collect()
        freed_memory = before_memory - self.get_memory_usage()
        self.logger.debug(
            "event=radar.memory_cleanup freed_mb=%.1f collected=%s",
            freed_memory,
            collected,
        )
        return freed_memory
