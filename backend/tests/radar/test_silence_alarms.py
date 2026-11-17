"""A reading that goes quieter than it has been for a day raises one alarm."""

import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from off_key_core.schemas.radar import RadarActivityStatus
from off_key_mqtt_radar.activity import ActivityTracker
from off_key_mqtt_radar.health_monitor import HealthMonitor
from off_key_mqtt_radar.models import MQTTMessage
from off_key_mqtt_radar.silence import SilenceAlarms, silence_limit

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
DAY = 86400.0


def _activity():
    return RadarActivityStatus(stale_after_seconds={"a": 60.0, "b": 30.0})


def _snapshot(heard=DAY, **ages):
    return {
        "sensor_ages_seconds": ages,
        "sensor_chargers": {"a": "pump", "b": "pump"},
        "sensor_heard_seconds": dict.fromkeys(ages, heard),
        # a once paused for a minute; b never for more than 10 seconds.
        "sensor_longest_gap_seconds": {"a": 60.0, "b": 10.0},
    }


def test_silence_needs_a_day_of_rhythm_and_outlasts_the_longest_gap():
    assert silence_limit(60.0, 60.0, DAY - 1) is None
    assert silence_limit(60.0, None, DAY) is None
    assert silence_limit(60.0, 60.0, DAY) == 90.0
    # Never sooner than the stale limit.
    assert silence_limit(60.0, 10.0, DAY) == 60.0


def test_a_reading_raises_once_per_silence():
    silence = SilenceAlarms()
    rows = silence.due(_activity(), _snapshot(a=120.0, b=1.0), service_id="m", now=NOW)
    assert rows == [
        {
            "charger_id": "pump",
            # It crossed its 90 second limit 30 seconds ago.
            "timestamp": NOW - timedelta(seconds=30),
            "telemetry_type": "a",
            "service_id": "m",
            "anomaly_type": "silence",
            "anomaly_value": 120.0,
            "value_type": "silence_seconds",
            "sensor_set": ["a"],
        }
    ]
    # Not stored yet: it is due again.
    assert silence.due(_activity(), _snapshot(a=125.0), service_id="m", now=NOW)
    silence.raised(rows)
    assert not silence.due(_activity(), _snapshot(a=130.0), service_id="m")
    # The reading speaks again, then goes quiet anew.
    assert not silence.due(_activity(), _snapshot(a=1.0), service_id="m")
    again = silence.due(_activity(), _snapshot(a=91.0), service_id="m")
    assert [row["telemetry_type"] for row in again] == ["a"]


def test_a_reading_heard_for_less_than_a_day_raises_nothing():
    snapshot = _snapshot(heard=DAY - 1, a=1000.0)
    assert SilenceAlarms().due(_activity(), snapshot, service_id="m") == []


def test_nothing_is_due_without_activity():
    assert SilenceAlarms().due(None, None, service_id="m") == []


def _send(tracker, clock, at):
    clock[0] = at
    tracker.record_input(
        "a",
        MQTTMessage(
            topic="telemetry/pump/a",
            payload=b"{}",
            timestamp=datetime.now(UTC),
            received_monotonic=at,
        ),
        "pump",
    )


def _hourly_bursts(tracker, clock, hours):
    """Every 10 seconds for five minutes, then quiet for 55, each hour."""
    for hour in range(hours):
        for second in range(0, 300, 10):
            _send(tracker, clock, hour * 3600.0 + second)


def test_the_tracker_remembers_a_days_longest_gap():
    clock = [0.0]
    tracker = ActivityTracker({"a"}, clock=lambda: clock[0])
    _hourly_bursts(tracker, clock, 2)
    snapshot = tracker.snapshot()
    assert snapshot["sensor_chargers"] == {"a": "pump"}
    assert snapshot["sensor_longest_gap_seconds"] == {"a": 3310.0}
    assert snapshot["sensor_heard_seconds"] == {"a": 3890.0}
    # Values every ten minutes for a day push the hourly pauses out.
    start = clock[0]
    for step in range(1, 160):
        _send(tracker, clock, start + step * 600.0)
    assert tracker.snapshot()["sensor_longest_gap_seconds"] == {"a": 600.0}


class _Writer:
    def __init__(self, stored=True):
        self.service_id = "monitor"
        self.stored = stored
        self.heartbeats = []

    async def write_heartbeat(self, metrics):
        self.heartbeats.append(metrics)
        return self.stored

    def get_health_status(self):
        return {}


def _monitor(writer, tracker):
    monitor = HealthMonitor()
    monitor.started_monotonic = time.monotonic()
    monitor.set_components(
        database_writer=writer,
        message_processor=SimpleNamespace(
            get_metrics=lambda: {"activity": tracker.snapshot()},
            # The stale limit learns the 10 second gap of a burst.
            stale_after_seconds=lambda: {"a": 30.0},
        ),
    )
    return monitor


async def _silences(monitor, writer, clock, at):
    clock[0] = at
    await monitor._perform_health_check()
    return len(writer.heartbeats[-1]["silence_alarms"])


@pytest.mark.asyncio
async def test_hourly_bursts_raise_nothing_until_a_longer_silence():
    clock = [0.0]
    tracker = ActivityTracker({"a"}, clock=lambda: clock[0])
    writer = _Writer(stored=False)
    monitor = _monitor(writer, tracker)
    _hourly_bursts(tracker, clock, 26)
    # Past the stale limit in its usual pause, and quiet for 55 minutes.
    last = clock[0]
    assert await _silences(monitor, writer, clock, last + 60) == 0
    assert await _silences(monitor, writer, clock, last + 3300) == 0
    # 1.5 times the 3310 second pause is 4965 seconds.
    assert await _silences(monitor, writer, clock, last + 5000) == 1
    # Not stored, so the next heartbeat carries it again.
    assert await _silences(monitor, writer, clock, last + 5100) == 1
    row = writer.heartbeats[-1]["silence_alarms"][0]
    assert (row["charger_id"], row["telemetry_type"], row["service_id"]) == (
        "pump",
        "a",
        "monitor",
    )
    writer.stored = True
    assert await _silences(monitor, writer, clock, last + 5200) == 1
    assert await _silences(monitor, writer, clock, last + 5300) == 0


async def _stored_silences(member_database, *, shadow):
    from off_key_core.db.models import MonitoringService, RadarRuntimeCheckpoint
    from off_key_mqtt_radar.config.config import RadarConfig
    from off_key_mqtt_radar.database import DatabaseWriter
    from off_key_mqtt_radar.tables import ANOMALY_IDENTITY_TABLE, ANOMALY_TABLE
    from sqlalchemy import insert, select

    from tests.support.form_pipeline import form_radar_config

    engine, sessions = member_database
    async with engine.begin() as connection:
        # RADAR's own tables, without the hypertable the core model adds.
        for table in (
            MonitoringService.__table__,
            RadarRuntimeCheckpoint.__table__,
            ANOMALY_TABLE,
            ANOMALY_IDENTITY_TABLE,
        ):
            await connection.run_sync(table.create)
        await connection.execute(
            insert(MonitoringService).values(
                id="monitor", container_name="monitor", mqtt_topic=[]
            )
        )
    config = form_radar_config(None, ["telemetry/pump/a"], RadarConfig, shadow=shadow)
    writer = DatabaseWriter(config, session_factory=sessions, service_id="monitor")
    silence = SilenceAlarms().due(
        _activity(), _snapshot(a=120.0), service_id="monitor", now=NOW
    )
    heartbeat = {
        "operational_status": {"stage": "degraded"},
        "silence_alarms": silence,
    }
    assert await writer.write_heartbeat(heartbeat)
    # A repeated heartbeat stores nothing twice.
    assert await writer.write_heartbeat(heartbeat)
    async with sessions() as session:
        rows = (await session.execute(select(ANOMALY_TABLE))).mappings().all()
        identities = (await session.execute(select(ANOMALY_IDENTITY_TABLE))).all()
    assert len(identities) == len(rows)
    return [dict(row) for row in rows]


@pytest.mark.asyncio
async def test_a_silence_is_stored_as_an_alarm(member_database):
    rows = await _stored_silences(member_database, shadow=False)
    assert [
        (
            row["telemetry_type"],
            row["anomaly_type"],
            row["value_type"],
            row["sensor_set"],
        )
        for row in rows
    ] == [("a", "silence", "silence_seconds", ["a"])]


@pytest.mark.asyncio
async def test_a_shadow_run_stores_no_silence(member_database):
    assert await _stored_silences(member_database, shadow=True) == []
