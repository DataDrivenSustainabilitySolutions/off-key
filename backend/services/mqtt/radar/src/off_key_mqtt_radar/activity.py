"""Track useful monitoring progress independently of heartbeats and counters."""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from off_key_core.schemas.radar import RadarActivityStatus

from .models import AnomalyResult, MQTTMessage


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
        self._last_input: _ActivityEvent | None = None
        self._last_processed: _ActivityEvent | None = None
        self._last_inference: _ActivityEvent | None = None
        self._processed_count = 0

    def record_input(self, sensor: str | None, message: MQTTMessage) -> None:
        now = self._clock()
        received_at = message.timestamp or datetime.now(UTC)
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=UTC)
        received_at = received_at.astimezone(UTC)
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

    def record_result(self, result: AnomalyResult) -> None:
        context = result.context or {}
        if context.get("fallback_reason") or context.get("service_state") == "failed":
            return
        event = _ActivityEvent(datetime.now(UTC), self._clock())
        is_inference = any(
            isinstance(context.get(key), dict) and context[key].get("phase") == phase
            for key, phase in (
                ("static_conformal", "ready"),
                ("adaptive_stream", "operational"),
            )
        )
        with self._lock:
            self._last_processed = event
            self._processed_count += 1
            if is_inference:
                self._last_inference = event

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
            }


def evaluate_activity(
    snapshot: dict[str, Any] | None,
    *,
    freshness_seconds: float,
    inference_expected: bool,
    database_health: dict[str, Any],
) -> RadarActivityStatus | None:
    """Apply the configured freshness budget to one current runtime snapshot."""
    if snapshot is None:
        return None
    required = set(snapshot["required_sensors"])
    sensor_ages = snapshot["sensor_ages_seconds"]
    missing = sorted(required - sensor_ages.keys())
    stale = sorted(
        sensor
        for sensor, age in sensor_ages.items()
        if (not required or sensor in required) and age > freshness_seconds
    )
    runtime_age = snapshot["runtime_age_seconds"]
    missing_after_grace = (
        bool(missing)
        and runtime_age > freshness_seconds
        and (snapshot.get("last_input_at") is not None or inference_expected)
    )
    inference_age = snapshot.get("last_inference_age_seconds")
    if inference_age is None:
        inference_age = snapshot.get("last_processed_age_seconds")
    if inference_age is None:
        inference_age = runtime_age
    persistence_age = database_health.get("oldest_pending_age_seconds")
    persistence_timeout = database_health.get(
        "persistence_timeout_seconds", freshness_seconds
    )
    return RadarActivityStatus(
        freshness_seconds=freshness_seconds,
        last_input_at=snapshot.get("last_input_at"),
        last_processed_at=snapshot.get("last_processed_at"),
        last_inference_at=snapshot.get("last_inference_at"),
        last_persisted_at=database_health.get("last_persisted_at"),
        missing_sensors=missing,
        stale_sensors=stale,
        inputs_stalled=bool(stale) or missing_after_grace,
        inference_stalled=inference_expected and inference_age > freshness_seconds,
        persistence_stalled=(
            isinstance(persistence_age, int | float)
            and persistence_age > persistence_timeout
        ),
    )
