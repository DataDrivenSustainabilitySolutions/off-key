"""Bounded chart views calculated from recorded measurements, never extrema."""

import typing
from datetime import UTC, datetime, timedelta
from math import ceil, log10
from typing import Literal

from off_key_core.db.models import Telemetry
from off_key_core.schemas.devices import (
    MeasurementBucket,
    MeasurementHistory,
    MeasurementSummary,
)
from sqlalchemy import Float, cast, func, select
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.ext.asyncio import AsyncSession

# Original readings per mean bucket: a pixel column is about a third of a bucket.
RAW_COLUMNS_PER_BUCKET = 3
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
        span_ms = (end - start).total_seconds() * 1000
        columns = buckets * RAW_COLUMNS_PER_BUCKET
        # Four readings per column draw the same line as every reading would.
        if view == "raw" and count > columns * 4:
            column_ms = history_interval(span_ms, columns, None)
            result.column_ms = column_ms
            result.points = await _thinned_readings(session, conditions, column_ms)
            return result
        rows = await session.execute(
            select(Telemetry.timestamp, Telemetry.value)
            .where(*conditions)
            .order_by(Telemetry.timestamp)
        )
        result.points = [
            MeasurementBucket(timestamp=time.isoformat(), value=value)
            for time, value in rows.all()
            if value is not None
        ]
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


async def _thinned_readings(
    session: AsyncSession, conditions: tuple, column_ms: int
) -> list[MeasurementBucket]:
    """Each column's first, last, lowest and highest original reading (M4).

    Columns start at the epoch, so the client can tell them apart. Every point is
    a real reading with its own time and value: a line through them covers the
    same pixels as one through every reading, and no spike is lost. One hashed
    aggregation finds all four, without sorting the range: arrays compare
    element by element, so ``[time, value]`` picks by time and ``[value, time]``
    by value, the earliest reading winning a tie.
    """
    column = func.date_bin(
        timedelta(milliseconds=column_ms), Telemetry.timestamp, EPOCH
    )
    time = cast(func.extract("epoch", Telemetry.timestamp), Float)
    value = cast(Telemetry.value, Float)
    rows = await session.execute(
        select(
            func.min(array([time, value])),
            func.max(array([time, value])),
            func.min(array([value, time])),
            func.max(array([value, -time])),
        )
        .where(*conditions)
        .group_by(column)
    )
    # Each row holds four [time, value] or [value, time] pairs.
    columns = typing.cast(list[tuple[list[float], ...]], rows.all())
    readings: dict[float, float] = {}
    for first, last, low, high in columns:
        readings[first[0]] = first[1]
        readings[last[0]] = last[1]
        readings[low[1]] = low[0]
        readings[-high[1]] = high[0]
    return [
        MeasurementBucket(
            timestamp=datetime.fromtimestamp(seconds, UTC).isoformat(), value=reading
        )
        for seconds, reading in sorted(readings.items())
    ]
