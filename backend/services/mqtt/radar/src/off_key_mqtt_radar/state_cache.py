"""
State cache for aligning multi-sensor MQTT streams.

Implements a "wait_for_all" strategy:
- Maintain the latest value per required sensor for each charger
- On every incoming message, update the cache for that sensor
- Emit a complete feature vector only when all required sensors
  have at least one value; use the latest value for each sensor.

This addresses cases where sensors report at different cadences by
always emitting the freshest complete combination once the slowest
sensor arrives.

Includes TTL-based cleanup to prevent memory growth from stale entries.
"""

from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Default TTL: 1 hour in seconds
DEFAULT_TTL_SECONDS = 3600
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
        max_chargers: int = DEFAULT_MAX_CHARGERS,
    ):
        """
        Initialize the sensor state cache.

        Args:
            required_sensors: Set of sensor types required for alignment
            ttl_seconds: Time-to-live for cache entries in seconds (default: 1 hour)
            max_chargers: Maximum number of chargers to cache (default: 10000)
        """
        self._lock = Lock()
        self.required_sensors = set(required_sensors)
        self.ttl_seconds = ttl_seconds
        self.max_chargers = max_chargers
        # cache[charger_id][sensor_type] = {"values": {...}, "timestamp": float}
        self.cache: Dict[str, Dict[str, Dict[str, object]]] = {}
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # Run cleanup every 5 minutes

    def update(
        self, charger_id: str, sensor_type: str, values: Dict[str, float]
    ) -> Optional[Dict[str, float]]:
        """
        Update cache with a new sensor reading.

        Returns a full feature vector (latest values for all required sensors)
        when every required sensor has at least one value. Otherwise returns None.

        Thread-safe: uses internal lock for concurrent access.
        """
        current_time = time.time()

        with self._lock:
            # Periodic cleanup
            if current_time - self._last_cleanup > self._cleanup_interval:
                self._cleanup_stale_entries(current_time)
                self._last_cleanup = current_time

            charger_cache = self.cache.setdefault(charger_id, {})
            charger_cache[sensor_type] = {
                "values": values,
                "timestamp": current_time,
            }

            if not self.required_sensors:
                # No alignment requested; emit the incoming values as-is
                return values

            if not self.required_sensors.issubset(charger_cache.keys()):
                return None  # Still waiting on at least one sensor

            aligned: Dict[str, float] = {}
            for sensor in self.required_sensors:
                latest = charger_cache[sensor]["values"]
                value = _extract_numeric_value(latest, sensor)
                if value is None:
                    logger.debug(
                        f"Failed to extract numeric value for sensor '{sensor}' "
                        f"from charger '{charger_id}': {latest}"
                    )
                    continue
                aligned[sensor] = value

            # If we somehow failed to extract any values, do not emit
            if not aligned:
                return None

            return aligned

    def _cleanup_stale_entries(self, current_time: float) -> None:
        """Remove stale cache entries based on TTL.

        Must be called while holding the lock.
        """
        stale_chargers: List[str] = []

        for charger_id, sensors in self.cache.items():
            # Find the most recent timestamp for this charger
            latest_timestamp = 0.0
            for sensor_data in sensors.values():
                ts = sensor_data.get("timestamp", 0)
                if ts > latest_timestamp:
                    latest_timestamp = ts

            # Mark as stale if all sensors are older than TTL
            if current_time - latest_timestamp > self.ttl_seconds:
                stale_chargers.append(charger_id)

        # Remove stale entries
        for charger_id in stale_chargers:
            del self.cache[charger_id]

        if stale_chargers:
            logger.info(f"Cleaned up {len(stale_chargers)} stale charger entries")

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

        logger.warning(
            f"Evicted {entries_to_remove} oldest charger entries "
            f"(max_chargers={self.max_chargers})"
        )

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self.cache.clear()

    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        with self._lock:
            total_sensors = sum(len(sensors) for sensors in self.cache.values())
            return {
                "chargers": len(self.cache),
                "total_sensor_entries": total_sensors,
                "max_chargers": self.max_chargers,
                "ttl_seconds": int(self.ttl_seconds),
            }
