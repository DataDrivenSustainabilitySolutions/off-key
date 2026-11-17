"""Raise one alarm when a reading goes quiet past its stale limit.

A monitor that hears nothing from a reading cannot score it, so its silence
would otherwise pass unseen in the alarm list. The health loop already judges
each reading against its own limit; this turns the moment a reading turns
stale into an alarm row. A reading raises again only after it has sent a
value and gone quiet anew.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from off_key_core.schemas.radar import RadarActivityStatus

SILENCE_ALARM_TYPE = "silence"
# The alarm's value is how long the reading had been quiet when it was noticed.
SILENCE_VALUE_TYPE = "silence_seconds"


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
        """Anomaly rows for readings that turned stale since they last raised."""
        if activity is None or snapshot is None:
            return []
        stale = set(activity.stale_sensors)
        # A reading that spoke again may raise for its next silence.
        self._raised &= stale
        now = now or datetime.now(UTC)
        ages = snapshot.get("sensor_ages_seconds") or {}
        chargers = snapshot.get("sensor_chargers") or {}
        rows = []
        for sensor in sorted(stale - self._raised):
            age = ages.get(sensor)
            limit = activity.stale_after_seconds.get(
                sensor, max(activity.stale_after_seconds.values(), default=0.0)
            )
            if age is None:
                continue
            rows.append(
                {
                    "charger_id": chargers.get(sensor) or "unknown",
                    # When the reading crossed its limit, not when it was noticed.
                    "timestamp": now - timedelta(seconds=max(age - limit, 0.0)),
                    "telemetry_type": sensor,
                    "service_id": service_id,
                    "anomaly_type": SILENCE_ALARM_TYPE,
                    "anomaly_value": round(age, 1),
                    "value_type": SILENCE_VALUE_TYPE,
                    "sensor_set": [sensor],
                }
            )
        return rows

    def raised(self, rows: list[dict[str, Any]]) -> None:
        """Mark the readings of stored rows as raised for this silence."""
        self._raised |= {row["telemetry_type"] for row in rows}
