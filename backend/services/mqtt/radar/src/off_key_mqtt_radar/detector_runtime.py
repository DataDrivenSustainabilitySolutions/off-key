"""One serial owner for CPU work and immutable, non-blocking health snapshots."""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from typing import Any, TypeVar

from .resilience import ResilientAnomalyDetector

T = TypeVar("T")


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
            self._snapshot = deepcopy(self.detector.get_health_info())

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
