"""Last-known-value alignment of a monitor's readings.

Readings arrive on their own topics, at their own rates and at their own
moments. An observation is formed from the latest value of every reading:

- Each reading's usual interval is learned from its own arrivals. Its last
  value stays usable for ``hold_intervals`` of those intervals, and never for
  less than ``minimum_hold_seconds``. A value that arrives older than that is
  rejected.
- An observation forms as soon as every reading has a new value. It waits for a
  reading only while that reading's next value is expected to arrive before the
  arriving reading's next one; otherwise it uses the reading's last value. This
  is judged by when values reach this worker, not by their observation time,
  because a sampler can forward one reading much later than another.
- An observation that would use a value older than its reading's limit, measured
  in observation time, is dropped, and the caller counts it.

A reading whose interval is not known yet, because it has arrived once, is
waited for and never held, so a monitor starts with fresh values only. Nothing
says yet when its next value is due, so none of its values is a gap: one of any
age is accepted, and one older than ``minimum_hold_seconds`` within an
observation is replaced by its next value instead of dropping the observation.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal

from off_key_core.schemas.radar import MonitorTiming
from off_key_core.utils.arrival_cadence import ArrivalCadence
from pydantic import FiniteFloat, TypeAdapter

DEFAULT_MAX_CHARGERS = 10000
DEFAULT_MAX_SENSOR_KEYS = 100


def _extract_numeric_value(values: dict[str, float], sensor_type: str) -> float | None:
    """The one number that represents this reading: its own key, ``value`` or
    the only value present."""
    if sensor_type in values and isinstance(values[sensor_type], int | float):
        return float(values[sensor_type])
    if "value" in values and isinstance(values["value"], int | float):
        return float(values["value"])
    if len(values) == 1:
        only_value = next(iter(values.values()))
        if isinstance(only_value, int | float):
            return float(only_value)
    return None


@dataclass(frozen=True, slots=True)
class _Reading:
    """The latest accepted value of one reading."""

    value: float
    event_timestamp: float
    # When this worker received it, on the receipt clock.
    received: float


@dataclass(slots=True)
class _Entity:
    readings: dict[str, _Reading] = field(default_factory=dict)
    cadences: dict[str, ArrivalCadence] = field(default_factory=dict)
    # Readings with a value no observation has used yet.
    fresh: set[str] = field(default_factory=set)


class SensorStateCache:
    """Accept observations per reading and form observations from them."""

    def __init__(
        self,
        required_sensors: set[str],
        timing: MonitorTiming | None = None,
        *,
        max_chargers: int = DEFAULT_MAX_CHARGERS,
        clock: Callable[[], float] | None = None,
        monotonic: Callable[[], float] | None = None,
    ):
        """
        Args:
            required_sensors: Feature keys of the readings an observation needs.
                Without any, every accepted value passes through on its own.
            timing: How long each reading's last value stays usable.
            clock, monotonic: Wall and receipt clocks. A Dojo replay passes the
                event time for both, so historical data ages as it did live.
        """
        self._clock = clock or time.time
        self._monotonic = monotonic or time.monotonic
        self._lock = Lock()
        self.timing = timing or MonitorTiming()
        self.required_sensors = set(required_sensors)
        self.required_sensor_order = tuple(sorted(self.required_sensors))
        self.max_chargers = max_chargers
        self._max_sensor_keys = max(DEFAULT_MAX_SENSOR_KEYS, len(self.required_sensors))
        self._entities: dict[str, _Entity] = {}
        self._watermarks: dict[str, dict[str, float]] = {}

    def update_with_status(
        self,
        charger_id: str,
        sensor_type: str,
        values: dict[str, float],
        *,
        sample_timestamp: float | None = None,
        received_monotonic: float | None = None,
    ) -> AlignmentUpdate:
        """Accept one reading's value and form an observation if one is due."""
        now = self._clock()
        event_timestamp = now if sample_timestamp is None else sample_timestamp
        received = (
            self._monotonic() if received_monotonic is None else received_monotonic
        )
        with self._lock:
            rejection = self._admission(
                charger_id, sensor_type, event_timestamp, received_monotonic, now
            )
            if rejection is not None:
                return AlignmentUpdate(
                    status="observation_rejected", rejection_reason=rejection
                )
            entity = self._entities.setdefault(charger_id, _Entity())
            # Every well-formed arrival teaches the reading's interval, also one
            # that is too old to use.
            cadence = entity.cadences.setdefault(sensor_type, ArrivalCadence())
            cadence.add(event_timestamp)
            interval = cadence.typical_seconds
            limit = self._limit(interval)
            if interval is not None and now - event_timestamp > limit:
                return AlignmentUpdate(
                    status="observation_rejected",
                    rejection_reason="observation_too_old",
                )
            if self._monotonic() - received > limit:
                return AlignmentUpdate(
                    status="observation_rejected", rejection_reason="receipt_too_old"
                )
            value = _extract_numeric_value(values, sensor_type)
            if self.required_sensors and value is None:
                return AlignmentUpdate(
                    status="observation_rejected",
                    rejection_reason="observation_without_value",
                )
            self._watermarks.setdefault(charger_id, {})[sensor_type] = event_timestamp
            if not self.required_sensors:
                return AlignmentUpdate(
                    status="aligned",
                    features=dict(values),
                    input_timestamps={sensor_type: event_timestamp},
                    sample_timestamp=event_timestamp,
                )
            # A reading that reports again before the observation formed
            # replaces its value: the observation keeps waiting for the others.
            entity.readings[sensor_type] = _Reading(value, event_timestamp, received)
            entity.fresh.add(sensor_type)
            return self._form(entity, sensor_type, received)

    def _admission(
        self,
        charger_id: str,
        sensor_type: str,
        timestamp: float,
        received_monotonic: float | None,
        now: float,
    ) -> str | None:
        """Why this arrival is not a new observation of a known reading."""
        if self.required_sensors and sensor_type not in self.required_sensors:
            return "observation_unexpected_sensor"
        if received_monotonic is not None and not math.isfinite(received_monotonic):
            return "receipt_nonfinite"
        if not math.isfinite(timestamp):
            return "observation_nonfinite"
        if timestamp - now > self.timing.future_tolerance_seconds:
            return "observation_in_future"
        watermarks = self._watermarks.get(charger_id, {})
        previous = watermarks.get(sensor_type)
        if previous is not None and timestamp <= previous:
            return (
                "observation_duplicate"
                if timestamp == previous
                else "observation_regression"
            )
        if (
            charger_id not in self._watermarks
            and len(self._watermarks) >= self.max_chargers
        ):
            return "observation_capacity"
        if sensor_type not in watermarks and len(watermarks) >= self._max_sensor_keys:
            return "observation_capacity"
        return None

    def _form(self, entity: _Entity, arriving: str, at: float) -> AlignmentUpdate:
        """The observation this arrival, received ``at``, completes, or why
        there is none yet."""
        sensor_ages = self._sensor_ages(entity)
        missing = tuple(
            sensor
            for sensor in self.required_sensor_order
            if sensor not in entity.readings
        )
        if missing:
            return AlignmentUpdate(
                status="missing_reading",
                missing_sensors=missing,
                sensor_ages=sensor_ages,
            )
        pending = [
            sensor
            for sensor in self.required_sensor_order
            if sensor not in entity.fresh
        ]
        due = tuple(
            sensor for sensor in pending if self._is_due(entity, sensor, arriving, at)
        )
        if due:
            return AlignmentUpdate(
                status="waiting_for_reading",
                pending_sensors=due,
                sensor_ages=sensor_ages,
            )
        input_timestamps = {
            sensor: entity.readings[sensor].event_timestamp
            for sensor in self.required_sensor_order
        }
        observed_at = max(input_timestamps.values())
        stale = tuple(
            sensor
            for sensor, timestamp in input_timestamps.items()
            if observed_at - timestamp > self._limit(self._interval(entity, sensor))
        )
        if stale and all(self._interval(entity, sensor) is None for sensor in stale):
            entity.fresh.difference_update(stale)
            return AlignmentUpdate(
                status="waiting_for_reading",
                pending_sensors=stale,
                sensor_ages=sensor_ages,
            )
        # Either way these values are used up: the next observation needs new ones.
        entity.fresh.clear()
        if stale:
            return AlignmentUpdate(
                status="stale_reading",
                stale_sensors=stale,
                sensor_ages=sensor_ages,
                input_timestamps=input_timestamps,
            )
        return AlignmentUpdate(
            status="aligned",
            features={
                sensor: entity.readings[sensor].value
                for sensor in self.required_sensor_order
            },
            held_sensors=tuple(pending),
            sensor_ages=sensor_ages,
            input_timestamps=input_timestamps,
            sample_timestamp=observed_at,
        )

    def _is_due(self, entity: _Entity, sensor: str, arriving: str, at: float) -> bool:
        """Whether to wait for ``sensor`` instead of using its last value.

        A reading is waited for while its next value is expected to arrive
        before the arriving reading's next one, and is not overdue by more than
        half its interval. Both are on the receipt clock: waiting is about when
        values reach this worker. A reading whose interval is not known yet is
        always waited for.
        """
        interval = self._interval(entity, sensor)
        if interval is None:
            return True
        expected = entity.readings[sensor].received + interval
        if expected <= at - interval / 2:
            return False
        arriving_interval = self._interval(entity, arriving)
        return arriving_interval is None or expected < at + arriving_interval

    @staticmethod
    def _interval(entity: _Entity | None, sensor: str) -> float | None:
        cadence = None if entity is None else entity.cadences.get(sensor)
        return None if cadence is None else cadence.typical_seconds

    def _limit(self, interval: float | None) -> float:
        """How old a reading's value may be when an observation uses it."""
        minimum = self.timing.minimum_hold_seconds
        if interval is None:
            return minimum
        return max(minimum, self.timing.hold_intervals * interval)

    def _sensor_ages(self, entity: _Entity) -> dict[str, float]:
        """Seconds since each cached value was received by this worker."""
        now = self._monotonic()
        return {
            sensor: max(now - reading.received, 0.0)
            for sensor, reading in entity.readings.items()
        }

    def stale_after_seconds(self) -> dict[str, float]:
        """Each reading's current limit, for health reporting: the required
        ones, or without any, every reading seen so far."""
        with self._lock:
            entities = list(self._entities.values())
            sensors = self.required_sensor_order or tuple(
                sorted({sensor for entity in entities for sensor in entity.cadences})
            )
            return {
                sensor: max(
                    (
                        self._limit(self._interval(entity, sensor))
                        for entity in entities
                    ),
                    default=self._limit(None),
                )
                for sensor in sensors
            }

    def export_watermarks(self) -> dict[str, dict[str, float]]:
        with self._lock:
            return {key: dict(values) for key, values in self._watermarks.items()}

    def restore_watermarks(self, payload: dict[str, dict[str, float]]) -> None:
        """Restore rejection history; values and learned intervals start over."""
        watermarks = TypeAdapter(dict[str, dict[str, FiniteFloat]]).validate_python(
            payload
        )
        with self._lock:
            merged = {key: dict(values) for key, values in self._watermarks.items()}
            for charger, sensors in watermarks.items():
                current = merged.setdefault(charger, {})
                for sensor, timestamp in sensors.items():
                    current[sensor] = max(timestamp, current.get(sensor, timestamp))
            if len(merged) > self.max_chargers or any(
                len(values) > self._max_sensor_keys for values in merged.values()
            ):
                raise ValueError(
                    "Observation watermark checkpoint exceeds cache capacity"
                )
            self._watermarks = merged
            self._entities.clear()


AlignmentStatus = Literal[
    "aligned",
    "missing_reading",
    "waiting_for_reading",
    "stale_reading",
    "observation_rejected",
]


@dataclass(frozen=True, slots=True)
class AlignmentUpdate:
    """Structured alignment outcome for observability and flow control."""

    status: AlignmentStatus
    features: dict[str, float] | None = None
    missing_sensors: tuple[str, ...] = ()
    pending_sensors: tuple[str, ...] = ()
    stale_sensors: tuple[str, ...] = ()
    # Readings whose earlier value this observation used again.
    held_sensors: tuple[str, ...] = ()
    sensor_ages: dict[str, float] = field(default_factory=dict)
    input_timestamps: dict[str, float] = field(default_factory=dict)
    sample_timestamp: float | None = None
    rejection_reason: str | None = None
