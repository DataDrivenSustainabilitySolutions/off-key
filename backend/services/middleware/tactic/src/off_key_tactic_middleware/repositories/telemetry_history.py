"""Bounded chart views calculated from recorded measurements, never extrema."""

from datetime import UTC, datetime, timedelta
from math import ceil, log10
from typing import Literal

from off_key_core.db.models import Telemetry
from off_key_core.schemas.devices import (
    MeasurementBucket,
    MeasurementHistory,
    MeasurementSummary,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

RAW_HISTORY_LIMIT = 10_000
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def history_interval(span_ms: float, buckets: int, minimum_ms: int | None) -> int:
    """Readable intervals with a stable epoch origin across live refreshes."""
    target = max(1, span_ms / buckets, minimum_ms or 0)
    intervals = (
        1,
        2,
        5,
        10,
        20,
        50,
        100,
        200,
        500,
        1000,
        2000,
        5000,
        10000,
        15000,
        30000,
        60000,
        120000,
        300000,
        600000,
        900000,
        1800000,
        3600000,
        7200000,
        21600000,
        43200000,
        86400000,
    )
    for interval in intervals:
        if interval >= target:
            return interval
    magnitude = 10 ** int(log10(target / 86400000))
    return ceil(target / (86400000 * magnitude)) * 86400000 * magnitude


async def read_history(
    session: AsyncSession,
    *,
    charger_id: str,
    telemetry_type: str,
    start: datetime,
    end: datetime,
    buckets: int,
    view: Literal["auto", "raw"],
    window_ms: int | None,
) -> MeasurementHistory:
    conditions = (
        Telemetry.charger_id == charger_id,
        Telemetry.type == telemetry_type,
        Telemetry.value.is_not(None),
        Telemetry.timestamp >= start,
        Telemetry.timestamp <= end,
    )
    count, first, last = (
        await session.execute(
            select(
                func.count(),
                func.min(Telemetry.timestamp),
                func.max(Telemetry.timestamp),
            ).where(*conditions)
        )
    ).one()
    if not count:
        return MeasurementHistory(representation="raw", points=[])
    result = MeasurementHistory(
        representation="raw",
        points=[],
        sample_count=count,
        extent=(first.isoformat(), last.isoformat()),
    )
    # Sparse views recover every original timestamp. An explicit averaging
    # window still applies to sparse numeric series.
    if view == "raw" or (window_ms is None and count <= buckets * 2):
        rows = await session.execute(
            select(Telemetry.timestamp, Telemetry.value)
            .where(*conditions)
            .order_by(Telemetry.timestamp.desc())
            .limit(RAW_HISTORY_LIMIT)
        )
        result.points = [
            MeasurementBucket(timestamp=time.isoformat(), value=value)
            for time, value in reversed(rows.all())
            if value is not None
        ]
        result.truncated = count > RAW_HISTORY_LIMIT
        return result

    interval_ms = history_interval(
        (end - start).total_seconds() * 1000, buckets, window_ms
    )
    width = timedelta(milliseconds=interval_ms)
    bucket = func.date_bin(width, Telemetry.timestamp, EPOCH)
    rows = await session.execute(
        select(
            bucket.label("bucket"),
            func.avg(Telemetry.value),
            func.min(Telemetry.value),
            func.max(Telemetry.value),
            func.count(),
        )
        .where(*conditions)
        .group_by(bucket)
        .order_by(bucket)
    )
    result.representation = "mean"
    result.interval_ms = interval_ms
    for time, mean, low, high, size in rows:
        assert low is not None and high is not None  # Query excludes null readings.
        left, right = max(time, start), min(time + width, end)
        result.points.append(
            MeasurementSummary(
                timestamp=(left + (right - left) / 2).isoformat(),
                value=mean,
                minimum=low,
                maximum=high,
                count=size,
                start=left.isoformat(),
                end=right.isoformat(),
            )
        )
    return result
