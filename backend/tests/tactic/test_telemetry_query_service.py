"""Tests for compact, cursor-based telemetry queries."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_tactic_middleware.domain import ValidationError
from off_key_tactic_middleware.repositories.data import TelemetryRepository
from off_key_tactic_middleware.services.data.telemetry import TelemetryQueryService


@pytest.mark.asyncio
async def test_forward_telemetry_query_pages_in_ingestion_order():
    cursor_created = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    cursor_timestamp = datetime(2026, 7, 27, 9, 59, tzinfo=UTC)
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    session.execute.return_value = result

    await TelemetryRepository(session).list_data(
        charger_id="charger-1",
        telemetry_type="voltage",
        limit=1000,
        after_timestamp=None,
        after_created=cursor_created,
        after_event_timestamp=cursor_timestamp,
    )

    query = str(session.execute.await_args.args[0])
    assert "telemetry.created >" in query
    assert "ORDER BY telemetry.created ASC, telemetry.timestamp ASC" in query


@pytest.mark.asyncio
async def test_telemetry_query_projects_values_and_forwards_cursor():
    cursor_created = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    cursor_timestamp = datetime(2026, 7, 27, 9, 59, tzinfo=UTC)
    timestamp = datetime(2026, 7, 27, 10, 0, 1, tzinfo=UTC)
    created = datetime(2026, 7, 27, 10, 0, 2, tzinfo=UTC)
    repository = AsyncMock()
    repository.list_data.return_value = [(timestamp, 42.5, created)]
    service = TelemetryQueryService(repository)

    result = await service.get_telemetry_data(
        charger_id="charger-1",
        telemetry_type="voltage",
        limit=1000,
        after_timestamp=None,
        after_created=cursor_created,
        after_event_timestamp=cursor_timestamp,
        paginated=False,
    )

    repository.list_data.assert_awaited_once_with(
        charger_id="charger-1",
        telemetry_type="voltage",
        limit=1000,
        after_timestamp=None,
        after_created=cursor_created,
        after_event_timestamp=cursor_timestamp,
    )
    assert result == [
        {
            "timestamp": timestamp.isoformat(),
            "value": 42.5,
            "created": created.isoformat(),
        }
    ]


@pytest.mark.asyncio
async def test_paginated_telemetry_returns_composite_ingestion_cursor():
    cursor_created = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
    cursor_timestamp = datetime(2026, 7, 27, 9, 59, tzinfo=UTC)
    first_timestamp = datetime(2026, 7, 27, 10, 1, tzinfo=UTC)
    first_created = datetime(2026, 7, 27, 10, 0, 1, tzinfo=UTC)
    last_timestamp = datetime(2026, 7, 27, 9, 58, tzinfo=UTC)
    last_created = datetime(2026, 7, 27, 10, 0, 2, tzinfo=UTC)
    repository = AsyncMock()
    repository.list_data.return_value = [
        (first_timestamp, 42.5, first_created),
        (last_timestamp, 41.5, last_created),
    ]

    result = await TelemetryQueryService(repository).get_telemetry_data(
        charger_id="charger-1",
        telemetry_type="voltage",
        limit=2,
        after_timestamp=None,
        after_created=cursor_created,
        after_event_timestamp=cursor_timestamp,
        paginated=True,
    )

    assert result["pagination"]["next_cursor"] == {
        "created": last_created.isoformat(),
        "timestamp": last_timestamp.isoformat(),
    }


@pytest.mark.asyncio
async def test_range_query_keeps_each_buckets_extremes_in_time_order():
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    session.execute.return_value = result

    await TelemetryRepository(session).list_range(
        charger_id="charger-1",
        telemetry_type="voltage",
        start=datetime(2026, 7, 27, tzinfo=UTC),
        end=datetime(2026, 7, 28, tzinfo=UTC),
        buckets=600,
    )

    query = str(session.execute.await_args.args[0])
    assert "date_bin" in query
    assert "row_number() OVER (PARTITION BY" in query
    assert "low = " in query and "high = " in query
    assert query.rstrip().endswith("ORDER BY anon_1.timestamp ASC")


@pytest.mark.asyncio
async def test_range_without_start_begins_at_the_first_stored_value():
    first = datetime(2026, 7, 20, tzinfo=UTC)
    end = datetime(2026, 7, 27, tzinfo=UTC)
    point = datetime(2026, 7, 21, tzinfo=UTC)
    repository = AsyncMock()
    repository.first_timestamp.return_value = first
    repository.list_range.return_value = [(point, 3.5)]

    result = await TelemetryQueryService(repository).get_telemetry_range(
        charger_id="charger-1",
        telemetry_type="voltage",
        start=None,
        end=end,
        buckets=600,
    )

    repository.list_range.assert_awaited_once_with(
        charger_id="charger-1",
        telemetry_type="voltage",
        start=first,
        end=end,
        buckets=600,
    )
    assert result == [{"timestamp": point.isoformat(), "value": 3.5}]


@pytest.mark.asyncio
async def test_range_of_an_unrecorded_series_is_empty():
    repository = AsyncMock()
    repository.first_timestamp.return_value = None

    result = await TelemetryQueryService(repository).get_telemetry_range(
        charger_id="charger-1",
        telemetry_type="voltage",
        start=None,
        end=None,
        buckets=600,
    )

    assert result == []
    repository.list_range.assert_not_awaited()


@pytest.mark.asyncio
async def test_inverted_range_is_rejected():
    repository = AsyncMock()
    with pytest.raises(ValidationError):
        await TelemetryQueryService(repository).get_telemetry_range(
            charger_id="charger-1",
            telemetry_type="voltage",
            start=datetime(2026, 7, 28, tzinfo=UTC),
            end=datetime(2026, 7, 27, tzinfo=UTC),
            buckets=600,
        )


@pytest.mark.asyncio
async def test_profile_reads_the_window_in_buckets_and_the_newest_values():
    repository = AsyncMock()
    now = datetime.now(UTC)
    repository.list_range.return_value = [
        (now - timedelta(hours=3), 1.0),
        (now - timedelta(hours=2), 5.0),
    ]
    # Newest first, as the table is read; one from before the window.
    repository.list_data.return_value = [
        (now - timedelta(seconds=10), 4.0, None),
        (now - timedelta(seconds=20), 2.0, None),
        (now - timedelta(days=9), 99.0, None),
    ]

    profile = await TelemetryQueryService(repository).get_reading_profile(
        reading_id="reading-1", charger_id="charger-1", telemetry_type="voltage", days=7
    )

    window = repository.list_range.await_args.kwargs
    assert (window["charger_id"], window["telemetry_type"]) == ("charger-1", "voltage")
    assert window["end"] - window["start"] == timedelta(days=7)
    # A quarter of an hour each, which is how the profile reads them again.
    assert window["buckets"] == 7 * 96
    assert repository.list_data.await_args.kwargs == {
        "charger_id": "charger-1",
        "telemetry_type": "voltage",
        "limit": 5000,
        "after_timestamp": None,
        "after_created": None,
        "after_event_timestamp": None,
    }
    assert profile.reading_id == "reading-1"
    assert (profile.start, profile.end) == (window["start"], window["end"])
    assert (profile.minimum, profile.maximum, profile.coverage) == (1, 5, 0.4)
    assert (profile.recent.count, profile.recent.mean) == (2, 3)
    assert profile.recent.interval_seconds == 10


@pytest.mark.asyncio
async def test_profile_of_a_long_window_stays_within_the_bucket_limit():
    repository = AsyncMock()
    repository.list_range.return_value = []
    repository.list_data.return_value = []

    profile = await TelemetryQueryService(repository).get_reading_profile(
        reading_id="reading-1",
        charger_id="charger-1",
        telemetry_type="voltage",
        days=90,
    )

    assert repository.list_range.await_args.kwargs["buckets"] == 2000
    assert profile.bucket_seconds == 3888
    assert profile.first is None and profile.recent is None
