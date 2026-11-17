"""A reading that goes quiet past its stale limit raises one alarm."""

import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from off_key_core.schemas.radar import RadarActivityStatus
from off_key_mqtt_radar.activity import ActivityTracker
from off_key_mqtt_radar.health_monitor import HealthMonitor
from off_key_mqtt_radar.models import MQTTMessage
from off_key_mqtt_radar.silence import SilenceAlarms

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _activity(*stale):
    return RadarActivityStatus(
        stale_after_seconds={"a": 60.0, "b": 30.0}, stale_sensors=list(stale)
    )


def _snapshot(**ages):
    return {
        "sensor_ages_seconds": ages,
        "sensor_chargers": {"a": "pump", "b": "pump"},
    }


def test_a_reading_raises_once_per_silence():
    silence = SilenceAlarms()
    rows = silence.due(
        _activity("a"), _snapshot(a=90.0, b=1.0), service_id="m", now=NOW
    )
    assert rows == [
        {
            "charger_id": "pump",
            # It crossed its 60 second limit 30 seconds ago.
            "timestamp": NOW - timedelta(seconds=30),
            "telemetry_type": "a",
            "service_id": "m",
            "anomaly_type": "silence",
            "anomaly_value": 90.0,
            "value_type": "silence_seconds",
            "sensor_set": ["a"],
        }
    ]
    # Not stored yet: it is due again.
    assert silence.due(_activity("a"), _snapshot(a=95.0), service_id="m", now=NOW)
    silence.raised(rows)
    assert not silence.due(_activity("a"), _snapshot(a=99.0), service_id="m")
    # The reading speaks again, then goes quiet anew.
    assert not silence.due(_activity(), _snapshot(a=1.0), service_id="m")
    again = silence.due(_activity("a"), _snapshot(a=61.0), service_id="m")
    assert [row["telemetry_type"] for row in again] == ["a"]


def test_nothing_is_due_without_activity():
    assert SilenceAlarms().due(None, None, service_id="m") == []


def test_the_tracker_names_the_device_a_reading_came_from():
    tracker = ActivityTracker({"a"})
    tracker.record_input(
        "a",
        MQTTMessage(topic="telemetry/pump/a", payload=b"{}"),
        "pump",
    )
    assert tracker.snapshot()["sensor_chargers"] == {"a": "pump"}


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


def _monitor(writer, clock):
    tracker = ActivityTracker({"a"}, clock=lambda: clock[0])
    tracker.record_input(
        "a",
        MQTTMessage(
            topic="telemetry/pump/a",
            payload=b"{}",
            timestamp=datetime.now(UTC),
            received_monotonic=clock[0],
        ),
        "pump",
    )
    monitor = HealthMonitor()
    monitor.started_monotonic = time.monotonic()
    monitor.set_components(
        database_writer=writer,
        message_processor=SimpleNamespace(
            get_metrics=lambda: {"activity": tracker.snapshot()},
            stale_after_seconds=lambda: {"a": 5.0},
        ),
    )
    return monitor


@pytest.mark.asyncio
async def test_the_heartbeat_carries_a_silence_until_it_is_stored():
    clock = [100.0]
    writer = _Writer(stored=False)
    monitor = _monitor(writer, clock)
    await monitor._perform_health_check()
    assert writer.heartbeats[-1]["silence_alarms"] == []
    clock[0] = 110.0
    await monitor._perform_health_check()
    await monitor._perform_health_check()
    # Not stored, so the next heartbeat carries it again.
    assert [len(beat["silence_alarms"]) for beat in writer.heartbeats] == [0, 1, 1]
    row = writer.heartbeats[-1]["silence_alarms"][0]
    assert (row["charger_id"], row["telemetry_type"], row["service_id"]) == (
        "pump",
        "a",
        "monitor",
    )
    writer.stored = True
    await monitor._perform_health_check()
    await monitor._perform_health_check()
    assert [len(beat["silence_alarms"]) for beat in writer.heartbeats[3:]] == [1, 0]


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
    config = form_radar_config(
        None, ["telemetry/pump/a"], RadarConfig, shadow=shadow
    )
    writer = DatabaseWriter(config, session_factory=sessions, service_id="monitor")
    silence = SilenceAlarms().due(
        _activity("a"), _snapshot(a=90.0), service_id="monitor", now=NOW
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
        (row["telemetry_type"], row["anomaly_type"], row["value_type"], row["sensor_set"])
        for row in rows
    ] == [("a", "silence", "silence_seconds", ["a"])]


@pytest.mark.asyncio
async def test_a_shadow_run_stores_no_silence(member_database):
    assert await _stored_silences(member_database, shadow=True) == []
