"""Evidence cursors order committed writes, including older transactions."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from aberration_core.db.models import MonitoringEvidence, MonitoringEvidenceClock
from aberration_core.db.schema import bootstrap_schema
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.ext.asyncio import create_async_engine


@pytest_asyncio.fixture
async def evidence_engine(disposable_database):
    with disposable_database.begin() as connection:
        bootstrap_schema(connection)
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    try:
        yield engine
    finally:
        await engine.dispose()


def observation(service):
    return (
        insert(MonitoringEvidence)
        .values(
            service_id=service,
            timestamp=datetime.now(UTC),
            sequence_number=1,
            charger_id="device",
            sensor_set=["reading"],
            input_timestamps={},
            strategy="adaptive_stream",
            anomaly_score=0.2,
            threshold=0.5,
        )
        .returning(MonitoringEvidence.created)
    )


@pytest.mark.asyncio
async def test_transaction_started_earlier_gets_a_cursor_after_later_commit(
    evidence_engine,
):
    async with evidence_engine.begin() as old:
        started = await old.scalar(text("SELECT now()"))
        async with evidence_engine.begin() as new:
            first = await new.scalar(observation("first"))
        second = await old.scalar(observation("second"))
        assert started < first < second
    async with evidence_engine.connect() as reader:
        assert list(
            await reader.scalars(
                select(MonitoringEvidence.service_id).where(
                    MonitoringEvidence.created > first
                )
            )
        ) == ["second"]


@pytest.mark.asyncio
async def test_watermark_waits_for_prior_writer_commit(evidence_engine):
    entered = asyncio.Event()

    async def later():
        async with evidence_engine.begin() as connection:
            entered.set()
            return await connection.scalar(observation("later"))

    async with evidence_engine.connect() as first:
        transaction = await first.begin()
        earlier = await first.scalar(observation("earlier"))
        task = asyncio.create_task(later())
        try:
            await entered.wait()
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), 0.1)
        finally:
            await transaction.commit()
        assert await task > earlier


@pytest.mark.asyncio
async def test_clock_remains_monotonic_after_retention_and_clock_regression(
    evidence_engine,
):
    future = datetime.now(UTC) + timedelta(days=1)
    async with evidence_engine.begin() as connection:
        await connection.execute(
            update(MonitoringEvidenceClock).values(last_created=future)
        )
        first = await connection.scalar(observation("first"))
        await connection.execute(delete(MonitoringEvidence))
    async with evidence_engine.begin() as connection:
        second = await connection.scalar(observation("second"))
    assert future < first < second
