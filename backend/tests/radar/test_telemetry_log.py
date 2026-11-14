"""The telemetry log a monitor reads: order, position and replay after restart."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from off_key_core.db.locks import TELEMETRY_LOG_LOCK
from off_key_core.db.migrate import apply_migrations
from off_key_mqtt_radar.telemetry_log import (
    LogClock,
    TelemetryLogReader,
    streams_from_topics,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.support.radar_pool import eventually

pytestmark = pytest.mark.radar_integration

START = datetime(2026, 11, 1, 12, tzinfo=UTC)


@pytest_asyncio.fixture
async def log_database(disposable_database):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def append(sessions, rows):
    """Append rows as the collector does: one transaction under the log lock."""
    async with sessions() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": TELEMETRY_LOG_LOCK}
        )
        for charger, key, offset, value in rows:
            await session.execute(
                text(
                    "INSERT INTO telemetry"
                    " (charger_id, timestamp, value, type, data_source)"
                    " VALUES (:charger, :timestamp, :value, :key, 'mqtt')"
                ),
                {
                    "charger": charger,
                    "timestamp": START + timedelta(seconds=offset),
                    "value": value,
                    "key": key,
                },
            )
        await session.commit()


def reader(sessions, topics, **options):
    return TelemetryLogReader(
        sessions, topics, clock=LogClock(), poll_seconds=0.01, **options
    )


async def drain(log, handled, count):
    async def done():
        return len(handled) >= count

    await log.start()
    try:
        await eventually(done, within=10, interval=0.01)
    finally:
        await log.stop()


def test_streams_are_the_accepted_topics_of_concrete_readings():
    assert streams_from_topics(["telemetry/b/x", "telemetry/a/y", "telemetry/a/y"]) == [
        ("a", "y"),
        ("b", "x"),
    ]
    for topic in ["telemetry/a/#", "telemetry/+/x", "raw/a/x", "telemetry/a"]:
        with pytest.raises(ValueError):
            streams_from_topics([topic])


async def test_reader_hands_over_its_own_streams_in_log_order(log_database):
    await append(log_database, [("a", "x", 0, 1.0), ("other", "x", 0, 9.0)])
    log = reader(log_database, ["telemetry/a/x", "telemetry/a/y"], batch_size=2)
    await log.place(0)
    await append(log_database, [("a", "y", 1, 2.0), ("a", "x", 2, 3.0)])
    handled = []

    async def handle(message):
        handled.append((message.topic, message.get_json_payload()["value"]))
        # The monitor's clock follows the time the reading was received.
        assert log.clock() == message.timestamp.timestamp()
        log.record_processed(message.log_seq)

    log.set_message_handler(handle)
    await drain(log, handled, 3)
    assert handled == [
        ("telemetry/a/x", 1.0),
        ("telemetry/a/y", 2.0),
        ("telemetry/a/x", 3.0),
    ]
    assert log.position == log.cursor
    assert log.get_health_status()["status"] == "healthy"


async def test_new_monitor_starts_after_the_newest_row(log_database):
    await append(log_database, [("a", "x", 0, 1.0), ("a", "x", 1, 2.0)])
    log = reader(log_database, ["telemetry/a/x"])
    await log.place(None)
    await append(log_database, [("a", "x", 2, 3.0)])
    handled = []

    async def handle(message):
        handled.append(message.get_json_payload()["value"])

    log.set_message_handler(handle)
    await drain(log, handled, 1)
    assert handled == [3.0]


async def test_restart_replays_every_reading_after_the_saved_position(log_database):
    """Readings processed after the checkpoint, and those logged while the
    monitor was down, are all handed to its successor exactly once."""
    await append(log_database, [("a", "x", offset, offset) for offset in range(3)])
    first = reader(log_database, ["telemetry/a/x"])
    await first.place(0)
    handled = []
    checkpoint = None

    async def handle(message):
        nonlocal checkpoint
        handled.append(message.get_json_payload()["value"])
        first.record_processed(message.log_seq)
        if len(handled) == 1:
            checkpoint = first.position

    first.set_message_handler(handle)
    await drain(first, handled, 3)
    # The monitor crashes after the third reading, with its checkpoint at the
    # first; two more readings arrive while it is down.
    await append(log_database, [("a", "x", offset, offset) for offset in (3, 4)])

    successor = reader(log_database, ["telemetry/a/x"])
    await successor.place(checkpoint)
    replayed = []

    async def replay(message):
        replayed.append(message.get_json_payload()["value"])

    successor.set_message_handler(replay)
    await drain(successor, replayed, 4)
    assert replayed == [1.0, 2.0, 3.0, 4.0]


async def test_a_large_backlog_is_read_in_batches_without_loss(log_database):
    log = reader(log_database, ["telemetry/a/x"], batch_size=7)
    await log.place(0)
    await append(log_database, [("a", "x", offset, offset) for offset in range(50)])
    handled = []

    async def handle(message):
        handled.append(message.get_json_payload()["value"])

    log.set_message_handler(handle)
    await drain(log, handled, 50)
    assert handled == [float(offset) for offset in range(50)]


async def test_positions_become_visible_in_commit_order(log_database):
    """A writer holding the lock delays every later position, so a reader never
    skips a smaller position that commits after a larger one."""
    log = reader(log_database, ["telemetry/a/x"])
    await log.place(0)
    holder = log_database()
    session = await holder.__aenter__()
    try:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": TELEMETRY_LOG_LOCK}
        )
        await session.execute(
            text(
                "INSERT INTO telemetry"
                " (charger_id, timestamp, value, type, data_source)"
                " VALUES ('a', :timestamp, 1, 'x', 'mqtt')"
            ),
            {"timestamp": START},
        )
        later = asyncio.create_task(append(log_database, [("a", "x", 1, 2.0)]))
        await asyncio.sleep(0.3)
        # The second writer waits for the lock; nothing is visible yet.
        assert not later.done()
        assert await log._read() == []
        await session.commit()
    finally:
        await holder.__aexit__(None, None, None)
    await later
    rows = await log._read()
    assert [row.value for row in rows] == [1.0, 2.0]
    assert rows[0].log_seq < rows[1].log_seq


async def test_read_failures_report_the_log_unavailable(log_database):
    def broken():
        raise RuntimeError("database gone")

    log = reader(broken, ["telemetry/a/x"])
    log.cursor = log.position = 0

    async def handle(message):
        raise AssertionError("nothing to hand over")

    log.set_message_handler(handle)
    await log.start()
    try:

        async def failed():
            return log.error_count

        await eventually(failed, within=10, interval=0.01)
        assert log.get_health_status()["reason"] == "log_unavailable"
    finally:
        await log.stop()
