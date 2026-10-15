"""One serial owner for CPU work and immutable, non-blocking health snapshots."""

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from typing import Any, TypeVar

from .resilience import ResilientAnomalyDetector

T = TypeVar("T")
logger = logging.getLogger(__name__)


class DetectorRuntime:
    """Serialize model reads, inference and checkpoint encoding off the event loop.

    The service has one bounded MQTT consumer and holds its processing lock over
    evidence/checkpoint commits. Health readers consume the last complete copy;
    they never race model mutation or wait for a long inference/serialization.
    """

    def __init__(self, detector: ResilientAnomalyDetector):
        self.detector = detector
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="radar-model"
        )
        self._submission_lock = asyncio.Lock()
        self._snapshot: dict[str, Any] = {}
        self._health_error_count = 0
        self._closed = False

    async def call(self, operation: Callable[..., T], *args: Any) -> T:
        async with self._submission_lock:
            if self._closed:
                raise RuntimeError("Detector runtime is closed")
            future = asyncio.get_running_loop().run_in_executor(
                self._executor, self._execute, operation, args
            )
            try:
                return await asyncio.shield(future)
            except asyncio.CancelledError:
                # Thread cancellation cannot interrupt a model mutation. Retain
                # ownership until the operation finishes before allowing shutdown.
                await future
                raise

    def _execute(self, operation: Callable[..., T], args: tuple[Any, ...]) -> T:
        try:
            return operation(*args)
        finally:
            # Diagnostics must never replace a completed inference result or its
            # original exception: the service still owns evidence for that result.
            self._refresh_snapshot()

    def _refresh_snapshot(self) -> None:
        try:
            snapshot = deepcopy(self.detector.get_health_info())
        except Exception as error:
            self._health_error_count += 1
            # The last snapshot is immutable. A shallow copy preserves its last
            # coherent model statistics without repeating a failing deep copy.
            snapshot = dict(self._snapshot)
            if snapshot.get("state") != "failed":
                snapshot["state"] = "degraded"
            snapshot["health_snapshot_error"] = f"{type(error).__name__}: {error}"
            logger.exception("event=radar.detector_health_snapshot_failed")
        else:
            snapshot["health_snapshot_error"] = None
        snapshot["health_snapshot_error_count"] = self._health_error_count
        self._snapshot = snapshot

    async def refresh(self) -> None:
        await self.call(lambda: None)

    def get_health_info(self) -> dict[str, Any]:
        return deepcopy(self._snapshot)

    async def stop(self) -> None:
        async with self._submission_lock:
            if self._closed:
                return
            self._closed = True
            await asyncio.to_thread(self._executor.shutdown, wait=True)
