"""Feed a monitor through the stored telemetry log, as the collector does."""

from datetime import datetime

import pytest_asyncio
from off_key_core.db.locks import TELEMETRY_LOG_LOCK
from off_key_core.db.migrate import apply_migrations
from off_key_mqtt_radar import database as radar_database
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_APPEND = text(
    "INSERT INTO telemetry (charger_id, timestamp, value, type, data_source)"
    " VALUES (:charger, :timestamp, :value, :key, 'mqtt')"
    " ON CONFLICT DO NOTHING"
)


def use_log(monkeypatch, sessions) -> None:
    """Monitors started in this test read the log, and write, through ``sessions``."""
    monkeypatch.setattr(radar_database, "_radar_async_session_factory", sessions)


@pytest_asyncio.fixture
async def telemetry_log(disposable_database, monkeypatch):
    """A migrated database whose telemetry log the monitors under test read."""
    with disposable_database.begin() as connection:
        apply_migrations(connection)
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    use_log(monkeypatch, sessions)
    try:
        yield sessions
    finally:
        await engine.dispose()


async def log_readings(
    sessions, readings: list[tuple[str, float | None, datetime]]
) -> None:
    """Append ``(topic, value, received_at)`` rows in one collector batch."""
    async with sessions() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": TELEMETRY_LOG_LOCK}
        )
        for topic, value, received_at in readings:
            _, charger, key = topic.split("/", 2)
            await session.execute(
                _APPEND,
                {
                    "charger": charger,
                    "key": key,
                    "value": value,
                    "timestamp": received_at,
                },
            )
        await session.commit()


async def log_reading(sessions, topic: str, value: float | None, received_at):
    await log_readings(sessions, [(topic, value, received_at)])
