"""Raise one alarm when a reading goes quieter than it has been for a day.

A monitor that hears nothing from a reading cannot score it, so its silence
would otherwise pass unseen in the alarm list. The stale limit that decides
whether a value is fresh enough to score is too short for this: a sensor that
sends for a few minutes every hour pauses far longer than its usual gap. A
reading is silent once it has sent nothing for ``SILENCE_FACTOR`` times the
longest gap it had over the last day, and never before its stale limit. A
reading the monitor has heard for less than a day raises nothing, since its
rhythm is not known yet. It raises again only after it has sent a value and
gone quiet anew.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from off_key_core.schemas.radar import RadarActivityStatus

from .activity import GAP_MEMORY_SECONDS

SILENCE_ALARM_TYPE = "silence"
# The alarm's value is how long the reading had been quiet when it was noticed.
SILENCE_VALUE_TYPE = "silence_seconds"
SILENCE_FACTOR = 1.5


def silence_limit(
    stale_after: float, longest_gap: float | None, heard: float
) -> float | None:
    """Seconds of quiet that count as silence; None while the rhythm is unknown."""
    if heard < GAP_MEMORY_SECONDS or longest_gap is None:
        return None
    return max(stale_after, SILENCE_FACTOR * longest_gap)


class SilenceAlarms:
    """Remember which readings have raised for their current silence."""

    def __init__(self) -> None:
        self._raised: set[str] = set()

    def due(
        self,
        activity: RadarActivityStatus | None,
        snapshot: dict[str, Any] | None,
        *,
        service_id: str,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Anomaly rows for readings that turned silent since they last raised."""
        if activity is None or snapshot is None:
            return []
        now = now or datetime.now(UTC)
        ages = snapshot.get("sensor_ages_seconds") or {}
        chargers = snapshot.get("sensor_chargers") or {}
        heard = snapshot.get("sensor_heard_seconds") or {}
        longest = snapshot.get("sensor_longest_gap_seconds") or {}
        budget = max(activity.stale_after_seconds.values(), default=0.0)
        silent: dict[str, tuple[float, float]] = {}
        for sensor, age in ages.items():
            limit = silence_limit(
                activity.stale_after_seconds.get(sensor, budget),
                longest.get(sensor),
                heard.get(sensor, 0.0),
            )
            if limit is not None and age > limit:
                silent[sensor] = (age, limit)
        # A reading that spoke again may raise for its next silence.
        self._raised &= silent.keys()
        return [
            {
                "charger_id": chargers.get(sensor) or "unknown",
                # When the reading crossed its limit, not when it was noticed.
                "timestamp": now - timedelta(seconds=age - limit),
                "telemetry_type": sensor,
                "service_id": service_id,
                "anomaly_type": SILENCE_ALARM_TYPE,
                "anomaly_value": round(age, 1),
                "value_type": SILENCE_VALUE_TYPE,
                "sensor_set": [sensor],
            }
            for sensor, (age, limit) in sorted(silent.items())
            if sensor not in self._raised
        ]

    def raised(self, rows: list[dict[str, Any]]) -> None:
        """Mark the readings of stored rows as raised for this silence."""
        self._raised |= {row["telemetry_type"] for row in rows}
