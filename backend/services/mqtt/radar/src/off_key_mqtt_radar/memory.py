"""Process-memory monitoring for the RADAR service."""

import gc
import logging
import os

import psutil


class MemoryManager:
    """Monitor process memory and trigger explicit garbage collection."""

    def __init__(
        self,
        max_memory_mb: float = 2000,
        cleanup_threshold: float = 0.8,
    ) -> None:
        self.max_memory_mb = max_memory_mb
        self.cleanup_threshold = cleanup_threshold
        self.process = psutil.Process(os.getpid())
        self.logger = logging.getLogger(__name__)

    def get_memory_usage(self) -> float:
        return self.process.memory_info().rss / 1024 / 1024

    def should_cleanup(self) -> bool:
        return self.get_memory_usage() > self.max_memory_mb * self.cleanup_threshold

    def force_cleanup(self) -> float:
        before_memory = self.get_memory_usage()
        collected = gc.collect()
        freed_memory = before_memory - self.get_memory_usage()
        self.logger.debug(
            "event=radar.memory_cleanup freed_mb=%.1f collected=%s",
            freed_memory,
            collected,
        )
        return freed_memory
