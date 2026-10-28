"""Downsampled telemetry ranges against an explicitly supplied TimescaleDB database."""

from datetime import UTC, datetime, timedelta

import pytest
from off_key_core.db.models import Telemetry
from off_key_core.db.schema import bootstrap_schema
from off_key_tactic_middleware.repositories.data import TelemetryRepository
from off_key_tactic_middleware.services.data.telemetry import TelemetryQueryService
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


@pytest.mark.asyncio
async def test_range_keeps_extremes_and_returns_sparse_rows_raw(disposable_database):
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    start = datetime(2026, 7, 27, tzinfo=UTC)
    rows = [
        {
            "charger_id": "range-test",
            "timestamp": start + timedelta(seconds=second),
            "value": 99.0 if second == 1234 else float(second % 7),
            "type": "voltage",
            "data_source": "test",
        }
        for second in range(3600)
    ]
    rows.append(rows[-1] | {"timestamp": start + timedelta(hours=2), "value": None})
    try:
        async with engine.begin() as connection:
            await connection.run_sync(bootstrap_schema)
            await connection.execute(insert(Telemetry), rows)
        async with AsyncSession(engine) as session:
            service = TelemetryQueryService(TelemetryRepository(session))
            stored = await service.get_telemetry_range(
                charger_id="range-test",
                telemetry_type="voltage",
                start=None,
                end=start + timedelta(hours=3),
                buckets=20,
            )
            sparse = await service.get_telemetry_range(
                charger_id="range-test",
                telemetry_type="voltage",
                start=start,
                end=start + timedelta(seconds=10),
                buckets=600,
            )
    finally:
        await engine.dispose()

    times = [point["timestamp"] for point in stored]
    assert len(stored) <= 40
    assert times == sorted(times)
    assert stored[0]["timestamp"] == start.isoformat()
    assert {
        "timestamp": (start + timedelta(seconds=1234)).isoformat(),
        "value": 99.0,
    } in stored
    assert all(point["value"] is not None for point in stored)
    assert [point["value"] for point in sparse] == [float(s % 7) for s in range(11)]
