"""Tests for compact, cursor-based telemetry queries."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
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
