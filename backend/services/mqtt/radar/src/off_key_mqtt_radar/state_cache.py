"""
State cache for aligning multi-sensor MQTT streams.

Uses strict barrier alignment semantics:
- emit one aligned sample only after all required sensors have produced at
  least one new value since the last emit for that charger.

Includes TTL-based cleanup to prevent memory growth from stale entries.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Default TTL: 1 hour in seconds
DEFAULT_TTL_SECONDS = 3600
# Default freshness gate for aligned sensor values
DEFAULT_MAX_SENSOR_AGE_SECONDS = 30.0
# Default max chargers to prevent unbounded growth
DEFAULT_MAX_CHARGERS = 10000


def _extract_numeric_value(
    values: Dict[str, float], sensor_type: str
) -> Optional[float]:
    """
    Extract a single numeric value to represent this sensor.
    Preference order:
    1) Explicit key matching the sensor type
    2) A "value" key
    3) The sole value if only one is present
    """
    if sensor_type in values and isinstance(values[sensor_type], (int, float)):
        return float(values[sensor_type])

    if "value" in values and isinstance(values["value"], (int, float)):
        return float(values["value"])

    if len(values) == 1:
        only_value = next(iter(values.values()))
        if isinstance(only_value, (int, float)):
            return float(only_value)

    return None


class SensorStateCache:
    """Caches latest sensor values per charger and emits aligned feature vectors.

    Includes TTL-based cleanup and max chargers limit to prevent memory growth.
    """

    def __init__(
        self,
        required_sensors: Set[str],
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_sensor_age_seconds: float = DEFAULT_MAX_SENSOR_AGE_SECONDS,
        max_chargers: int = DEFAULT_MAX_CHARGERS,
        alignment_mode: str = "strict_barrier",
    ):
        """
        Initialize the sensor state cache.

        Args:
            required_sensors: Set of sensor types required for alignment
            ttl_seconds: Time-to-live for cache entries in seconds (default: 1 hour)
            max_sensor_age_seconds: Maximum allowed age for each required sensor
                when emitting aligned vectors
            max_chargers: Maximum number of chargers to cache (default: 10000)
            alignment_mode: Must be "strict_barrier".
        """
        self._lock = Lock()
        self.required_sensors = set(required_sensors)
        self.required_sensor_order = tuple(sorted(self.required_sensors))
        self.ttl_seconds = ttl_seconds
        self.max_sensor_age_seconds = max(float(max_sensor_age_seconds), 0.1)
        self.max_chargers = max_chargers
        self.alignment_mode = alignment_mode.strip().lower()
        if self.alignment_mode != "strict_barrier":
            raise ValueError("alignment_mode must be: strict_barrier")
        # cache[charger_id][sensor_type] = {"values": {...}, "timestamp": float}
        self.cache: Dict[str, Dict[str, Dict[str, object]]] = {}
        # Tracks last emitted sensor update sequence in strict-barrier mode.
        self._last_emitted_versions: Dict[str, Dict[str, int]] = {}
        self._next_update_seq = 0
        self.strict_barrier_emit_count = 0
        self.strict_barrier_wait_count = 0
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # Run cleanup every 5 minutes

    def update(
        self, charger_id: str, sensor_type: str, values: Dict[str, float]
    ) -> Optional[Dict[str, float]]:
        """Backward-compatible shorthand for update_with_status()."""
        update = self.update_with_status(charger_id, sensor_type, values)
        return update.features

    def update_with_status(
        self, charger_id: str, sensor_type: str, values: Dict[str, float]
    ) -> "AlignmentUpdate":
        """
        Update cache with a new sensor reading.

        Returns a full feature vector (latest values for all required sensors)
        when every required sensor has at least one fresh value.

        Thread-safe: uses internal lock for concurrent access.
        """
        current_time = time.time()

        with self._lock:
            # Periodic cleanup
            if current_time - self._last_cleanup > self._cleanup_interval:
                self._cleanup_stale_entries(current_time)
                self._last_cleanup = current_time

            charger_cache = self.cache.setdefault(charger_id, {})
            self._next_update_seq += 1
            charger_cache[sensor_type] = {
                "values": values,
                "timestamp": current_time,
                "seq": self._next_update_seq,
            }

            if not self.required_sensors:
                # No alignment requested; emit the incoming values as-is
                return AlignmentUpdate(status="aligned_emit", features=values)

            missing_sensors = sorted(self.required_sensors - charger_cache.keys())
            sensor_ages = self._collect_sensor_ages(charger_cache, current_time)
            if missing_sensors:
                return AlignmentUpdate(
                    status="waiting_for_all",
                    missing_sensors=tuple(missing_sensors),
                    sensor_ages=sensor_ages,
                )

            stale_sensors = sorted(
                sensor
                for sensor, age in sensor_ages.items()
                if age > self.max_sensor_age_seconds
            )
            if stale_sensors:
                return AlignmentUpdate(
                    status="stale_sensor_block",
                    stale_sensors=tuple(stale_sensors),
                    sensor_ages=sensor_ages,
                )

            pending_sensors: List[str] = []
            last_emitted = self._last_emitted_versions.setdefault(charger_id, {})
            for sensor in self.required_sensor_order:
                current_seq = int(charger_cache[sensor].get("seq", 0))
                if current_seq <= int(last_emitted.get(sensor, 0)):
                    pending_sensors.append(sensor)
            if pending_sensors:
                self.strict_barrier_wait_count += 1
                return AlignmentUpdate(
                    status="waiting_for_barrier",
                    pending_sensors=tuple(pending_sensors),
                    sensor_ages=sensor_ages,
                )

            aligned: Dict[str, float] = {}
            for sensor in self.required_sensor_order:
                latest = charger_cache[sensor]["values"]
                value = _extract_numeric_value(latest, sensor)
                if value is None:
                    logger.debug(
                        "event=radar.sensor_value_extract_failed \
                            sensor=%s charger_id=%s values=%s",
                        sensor,
                        charger_id,
                        latest,
                    )
                    return AlignmentUpdate(
                        status="waiting_for_all",
                        missing_sensors=(sensor,),
                        sensor_ages=sensor_ages,
                    )
                aligned[sensor] = value

            last_emitted = self._last_emitted_versions.setdefault(charger_id, {})
            for sensor in self.required_sensor_order:
                last_emitted[sensor] = int(charger_cache[sensor].get("seq", 0))
            self.strict_barrier_emit_count += 1

            return AlignmentUpdate(
                status="aligned_emit",
                features=aligned,
                sensor_ages=sensor_ages,
                sample_timestamp=current_time,
            )

    def _collect_sensor_ages(
        self, charger_cache: Dict[str, Dict[str, object]], current_time: float
    ) -> Dict[str, float]:
        """Collect age in seconds for each required sensor that has a cached value."""
        ages: Dict[str, float] = {}
        for sensor in self.required_sensors:
            sensor_entry = charger_cache.get(sensor)
            if not sensor_entry:
                continue
            timestamp = float(sensor_entry.get("timestamp", current_time))
            ages[sensor] = max(current_time - timestamp, 0.0)
        return ages

    def _cleanup_stale_entries(self, current_time: float) -> None:
        """Remove stale cache entries based on TTL.

        Must be called while holding the lock.
        """
        stale_chargers: List[str] = []
        stale_sensor_entries = 0

        for charger_id, sensors in self.cache.items():
            stale_sensors = [
                sensor_name
                for sensor_name, sensor_data in sensors.items()
                if current_time - float(sensor_data.get("timestamp", 0))
                > self.ttl_seconds
            ]
            for sensor_name in stale_sensors:
                stale_sensor_entries += 1
                del sensors[sensor_name]

            if not sensors:
                stale_chargers.append(charger_id)

        # Remove stale entries
        for charger_id in stale_chargers:
            del self.cache[charger_id]
            self._last_emitted_versions.pop(charger_id, None)

        if stale_sensor_entries or stale_chargers:
            logger.debug(
                "Cleaned stale sensor cache entries",
                extra={
                    "stale_sensor_entries": stale_sensor_entries,
                    "stale_chargers": len(stale_chargers),
                },
            )

        # Enforce max chargers limit by removing oldest entries
        if len(self.cache) > self.max_chargers:
            self._evict_oldest_entries()

    def _evict_oldest_entries(self) -> None:
        """Evict oldest entries when max_chargers limit is exceeded.

        Must be called while holding the lock.
        """
        # Build list of (charger_id, latest_timestamp)
        charger_times: List[Tuple[str, float]] = []
        for charger_id, sensors in self.cache.items():
            latest_ts = max(
                (s.get("timestamp", 0) for s in sensors.values()),
                default=0,
            )
            charger_times.append((charger_id, latest_ts))

        # Sort by timestamp (oldest first)
        charger_times.sort(key=lambda x: x[1])

        # Remove oldest entries to get under limit
        entries_to_remove = len(self.cache) - self.max_chargers
        for i in range(entries_to_remove):
            charger_id = charger_times[i][0]
            del self.cache[charger_id]
            self._last_emitted_versions.pop(charger_id, None)

        logger.warning(
            "event=radar.sensor_cache_evicted count=%s max_chargers=%s",
            entries_to_remove,
            self.max_chargers,
        )

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self.cache.clear()
            self._last_emitted_versions.clear()

    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        with self._lock:
            total_sensors = sum(len(sensors) for sensors in self.cache.values())
            return {
                "chargers": len(self.cache),
                "total_sensor_entries": total_sensors,
                "max_chargers": self.max_chargers,
                "ttl_seconds": int(self.ttl_seconds),
                "max_sensor_age_seconds": self.max_sensor_age_seconds,
                "alignment_mode": self.alignment_mode,
                "strict_barrier_emit_count": self.strict_barrier_emit_count,
                "strict_barrier_wait_count": self.strict_barrier_wait_count,
            }


@dataclass(frozen=True)
class AlignmentUpdate:
    """Structured alignment outcome for observability and flow control."""

    status: str
    features: Optional[Dict[str, float]] = None
    missing_sensors: Tuple[str, ...] = ()
    pending_sensors: Tuple[str, ...] = ()
    stale_sensors: Tuple[str, ...] = ()
    sensor_ages: Dict[str, float] = field(default_factory=dict)
    sample_timestamp: Optional[float] = None
