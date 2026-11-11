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
    # The schema's retention job runs within a second of the commit and deletes rows
    # older than the retention window, so the range starts at yesterday's midnight.
    start = datetime.now(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=1)
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


@pytest.mark.asyncio
async def test_history_means_use_every_sample_and_raw_is_explicitly_bounded(
    disposable_database,
):
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    start = datetime.now(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=1)
    rows = [
        {
            "charger_id": "history-test",
            "timestamp": start + timedelta(milliseconds=i * 100),
            "value": 0.1 if i % 10 == 0 else 0,
            "type": "voltage",
            "data_source": "test",
        }
        for i in range(12000)
        if not 3000 <= i < 3600
    ]
    try:
        async with engine.begin() as connection:
            await connection.run_sync(bootstrap_schema)
            await connection.execute(insert(Telemetry), rows)
            await connection.execute(
                insert(Telemetry), [rows[0] | {"type": "other", "value": 999}]
            )
        async with AsyncSession(engine) as session:
            service = TelemetryQueryService(TelemetryRepository(session))
            args = dict(
                charger_id="history-test",
                telemetry_type="voltage",
                start=start,
                end=start + timedelta(seconds=1200),
                buckets=100,
            )
            overview = await service.get_telemetry_range(**args, view="auto")
            raw = await service.get_telemetry_range(**args, view="raw")
            zoomed = await service.get_telemetry_range(
                **(
                    args
                    | {
                        "start": start + timedelta(seconds=100),
                        "end": start + timedelta(seconds=100.8),
                    }
                ),
                view="auto",
            )
            refreshed = await service.get_telemetry_range(
                **(
                    args
                    | {
                        "start": start + timedelta(seconds=0.4),
                        "end": start + timedelta(seconds=1201),
                    }
                ),
                view="auto",
            )
    finally:
        await engine.dispose()

    assert overview.representation == "mean"
    assert overview.sample_count == 11400
    assert overview.interval_ms == 15000
    first = overview.points[0]
    assert first.value == pytest.approx(
        0.01
    )  # Averaging only min/max would incorrectly yield .05.
    assert first.minimum == 0 and first.maximum == 0.1 and first.count == 150
    assert sum(point.count for point in overview.points) == overview.sample_count
    assert len(overview.points) == 76  # Four empty 15-second buckets stay empty.
    assert overview.points[1] == refreshed.points[1]
    assert raw.representation == "raw" and raw.truncated
    assert len(raw.points) == 10000 and raw.sample_count == 11400
    assert all(point.value in (0, 0.1) for point in raw.points)
    assert raw.points[-1].timestamp == rows[-1]["timestamp"].isoformat()
    assert raw.extent == (
        rows[0]["timestamp"].isoformat(),
        rows[-1]["timestamp"].isoformat(),
    )
    assert zoomed.representation == "raw" and not zoomed.truncated
    assert len(zoomed.points) == 9
    assert zoomed.points[1].timestamp == (start + timedelta(seconds=100.1)).isoformat()
