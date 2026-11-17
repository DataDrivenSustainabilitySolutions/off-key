"""Track useful monitoring progress independently of heartbeats and counters."""

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from off_key_core.schemas.radar import MonitorTiming, RadarActivityStatus
from off_key_core.utils.timestamps import as_utc

from .models import AnomalyResult, MQTTMessage, is_held_back, is_inference

# How far back a reading's longest gap is remembered, kept as one maximum per hour.
GAP_MEMORY_SECONDS = 86400.0
_GAP_BUCKET_SECONDS = 3600.0


class _GapMemory:
    """The longest gap between a reading's values over the last day.

    One maximum per hour keeps the memory small at any arrival rate.
    """

    __slots__ = ("first", "hours")

    def __init__(self, first: float):
        self.first = first
        self.hours: deque[tuple[int, float]] = deque()

    def add(self, gap: float, at: float) -> None:
        hour = int(at // _GAP_BUCKET_SECONDS)
        if self.hours and self.hours[-1][0] == hour:
            self.hours[-1] = (hour, max(self.hours[-1][1], gap))
        else:
            self.hours.append((hour, gap))
        self._forget(at)

    def _forget(self, now: float) -> None:
        oldest = int((now - GAP_MEMORY_SECONDS) // _GAP_BUCKET_SECONDS)
        while self.hours and self.hours[0][0] < oldest:
            self.hours.popleft()

    def longest(self, now: float) -> float | None:
        self._forget(now)
        return max((gap for _, gap in self.hours), default=None)


@dataclass(frozen=True, slots=True)
class _ActivityEvent:
    at: datetime
    monotonic: float


class ActivityTracker:
    """Publish short immutable snapshots while one worker owns detector work.

    Monotonic receipt clocks include queue delay and remain local to this runtime.
    Restored detector counters cannot establish current input or scoring activity.
    """

    def __init__(
        self,
        required_sensors: set[str],
        *,
        clock: Callable[[], float] | None = None,
    ):
        self._lock = Lock()
        self._clock = clock or time.monotonic
        self._started = self._clock()
        self._required_sensors = frozenset(required_sensors)
        self._inputs: dict[str, _ActivityEvent] = {}
        # The device each reading last came from, so a silence alarm names it.
        self._chargers: dict[str, str] = {}
        self._gaps: dict[str, _GapMemory] = {}
        self._last_input: _ActivityEvent | None = None
        self._last_processed: _ActivityEvent | None = None
        self._last_inference: _ActivityEvent | None = None
        self._last_held_back: _ActivityEvent | None = None
        self._processed_count = 0

    def record_input(
        self,
        sensor: str | None,
        message: MQTTMessage,
        charger_id: str | None = None,
    ) -> None:
        now = self._clock()
        received_at = as_utc(message.timestamp or datetime.now(UTC))
        receipt_clock = getattr(message, "received_monotonic", None)
        if not isinstance(receipt_clock, int | float) or not math.isfinite(
            receipt_clock
        ):
            # Older producers of MQTTMessage still carry their UTC receipt time.
            elapsed = max((datetime.now(UTC) - received_at).total_seconds(), 0.0)
            receipt_clock = now - elapsed
        event = _ActivityEvent(received_at, min(float(receipt_clock), now))
        with self._lock:
            if (
                self._last_input is None
                or event.monotonic >= self._last_input.monotonic
            ):
                self._last_input = event
            if sensor is not None:
                previous = self._inputs.get(sensor)
                if previous is None or event.monotonic >= previous.monotonic:
                    self._inputs[sensor] = event
                    gaps = self._gaps.setdefault(sensor, _GapMemory(event.monotonic))
                    if previous is not None:
                        gaps.add(event.monotonic - previous.monotonic, event.monotonic)
                    if charger_id:
                        self._chargers[sensor] = charger_id

    def record_result(self, result: AnomalyResult) -> None:
        context = result.context or {}
        event = _ActivityEvent(datetime.now(UTC), self._clock())
        with self._lock:
            self._last_processed = event
            self._processed_count += 1
            if is_inference(context):
                self._last_inference = event
            elif is_held_back(context):
                self._last_held_back = event

    def snapshot(self) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            return {
                "runtime_age_seconds": max(now - self._started, 0.0),
                "required_sensors": sorted(self._required_sensors),
                "processed_count": self._processed_count,
                "sensor_ages_seconds": {
                    sensor: max(now - event.monotonic, 0.0)
                    for sensor, event in self._inputs.items()
                },
                "sensor_chargers": dict(self._chargers),
                # For silence alarms: how long each reading has been heard,
                # and the longest it went quiet over the last day.
                "sensor_heard_seconds": {
                    sensor: max(now - gaps.first, 0.0)
                    for sensor, gaps in self._gaps.items()
                },
                "sensor_longest_gap_seconds": {
                    sensor: longest
                    for sensor, gaps in self._gaps.items()
                    if (longest := gaps.longest(now)) is not None
                },
                "last_input_at": self._last_input.at if self._last_input else None,
                "last_processed_at": self._last_processed.at
                if self._last_processed
                else None,
                "last_inference_at": self._last_inference.at
                if self._last_inference
                else None,
                "last_inference_age_seconds": max(
                    now - self._last_inference.monotonic, 0.0
                )
                if self._last_inference
                else None,
                "last_processed_age_seconds": max(
                    now - self._last_processed.monotonic, 0.0
                )
                if self._last_processed
                else None,
                "last_held_back_age_seconds": max(
                    now - self._last_held_back.monotonic, 0.0
                )
                if self._last_held_back
                else None,
            }


def evaluate_activity(
    snapshot: dict[str, Any] | None,
    *,
    stale_after_seconds: dict[str, float],
    inference_expected: bool,
    database_health: dict[str, Any],
) -> RadarActivityStatus | None:
    """Judge one runtime snapshot against each reading's own staleness limit.

    The monitor as a whole is given as long as its slowest reading: no input,
    observation or inference within that budget means progress has stalled.
    """
    if snapshot is None:
        return None
    budget = max(
        stale_after_seconds.values(), default=MonitorTiming().minimum_hold_seconds
    )
    required = set(snapshot["required_sensors"])
    sensor_ages = snapshot["sensor_ages_seconds"]
    missing = sorted(required - sensor_ages.keys())
    stale = sorted(
        sensor
        for sensor, age in sensor_ages.items()
        if (not required or sensor in required)
        and age > stale_after_seconds.get(sensor, budget)
    )
    runtime_age = snapshot["runtime_age_seconds"]
    missing_after_grace = (
        bool(missing)
        and runtime_age > budget
        and (snapshot.get("last_input_at") is not None or inference_expected)
    )
    inference_age = snapshot.get("last_inference_age_seconds")
    if inference_age is None:
        inference_age = snapshot.get("last_processed_age_seconds")
    if inference_age is None:
        inference_age = runtime_age
    # A Gate that holds observations back works as designed; scoring resumes
    # when its condition holds again.
    held_back_age = snapshot.get("last_held_back_age_seconds")
    if held_back_age is not None:
        inference_age = min(inference_age, held_back_age)
    persistence_age = database_health.get("oldest_pending_age_seconds")
    persistence_timeout = database_health.get("persistence_timeout_seconds", budget)
    return RadarActivityStatus(
        stale_after_seconds=stale_after_seconds,
        last_input_at=snapshot.get("last_input_at"),
        last_processed_at=snapshot.get("last_processed_at"),
        last_inference_at=snapshot.get("last_inference_at"),
        last_persisted_at=database_health.get("last_persisted_at"),
        missing_sensors=missing,
        stale_sensors=stale,
        inputs_stalled=bool(stale) or missing_after_grace,
        inference_stalled=inference_expected and inference_age > budget,
        persistence_stalled=(
            isinstance(persistence_age, int | float)
            and persistence_age > persistence_timeout
        ),
    )
