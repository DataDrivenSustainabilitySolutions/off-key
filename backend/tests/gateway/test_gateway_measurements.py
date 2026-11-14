"""Device, measurement and evidence reads validate their input and ask the
catalogue data by catalogue id, with times in UTC."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_api_gateway.api.rate_limiter import limiter
from off_key_api_gateway.providers import get_catalogue_data_service

from tests.support.gateway import gateway_app, member, returning
from tests.support.http import asgi_client

MIDNIGHT = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def data():
    service = AsyncMock()
    for method in (
        "devices",
        "measurements",
        "measurement_buckets",
        "evidence",
        "chart_evidence",
    ):
        getattr(service, method).return_value = []
    service.device_readings = MagicMock(return_value=[])
    yield service
    limiter.reset()


@pytest.fixture
def get(data):
    async def read(path, **params):
        app = gateway_app(
            member(), overrides={get_catalogue_data_service: returning(data)}
        )
        async with asgi_client(app) as client:
            return await client.get(f"/v1/{path}", params=params)

    return read


@pytest.mark.asyncio
async def test_devices_filter_by_activity_only_when_asked(get, data):
    assert (await get("devices")).status_code == 200
    assert data.devices.await_args.kwargs == {"active": None}
    assert (await get("devices", active="true")).status_code == 200
    assert data.devices.await_args.kwargs == {"active": True}


@pytest.mark.asyncio
async def test_device_readings_name_an_encoded_device(get, data):
    response = await get("devices/site 1/readings")

    assert response.status_code == 200
    assert data.device_readings.call_args.args == ("site 1",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cursor", "asked"),
    [
        pytest.param({}, {}, id="first-page"),
        pytest.param(
            {"after_timestamp": "2026-01-01T02:00:00+02:00"},
            {"after_timestamp": MIDNIGHT},
            id="history",
        ),
        pytest.param(
            {
                "after_created": "2026-01-01T01:00:00+01:00",
                "after_event_timestamp": "2025-12-31T19:00:00-05:00",
            },
            {"after_created": MIDNIGHT, "after_event_timestamp": MIDNIGHT},
            id="live",
        ),
    ],
)
async def test_measurement_cursors_are_read_in_utc(get, data, cursor, asked):
    response = await get(
        "readings/stream:1/measurements", limit=50, paginated="true", **cursor
    )

    assert response.status_code == 200
    assert data.measurements.await_args.args == ("stream:1",)
    assert (
        data.measurements.await_args.kwargs
        == {
            "limit": 50,
            "after_timestamp": None,
            "after_created": None,
            "after_event_timestamp": None,
            "paginated": True,
        }
        | asked
    )
    for value in data.measurements.await_args.kwargs.values():
        if isinstance(value, datetime):
            assert value.utcoffset().total_seconds() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cursor", "detail"),
    [
        (
            {"after_created": "2026-01-01T00:00:00Z"},
            "All measurement live cursor fields are required",
        ),
        (
            {"after_event_timestamp": "2026-01-01T00:00:00Z"},
            "All measurement live cursor fields are required",
        ),
        (
            {
                "after_timestamp": "2026-01-01T00:00:00Z",
                "after_created": "2026-01-01T00:00:00Z",
                "after_event_timestamp": "2026-01-01T00:00:00Z",
            },
            "Historical and live measurement cursors cannot be used together",
        ),
    ],
)
async def test_inconsistent_cursors_are_refused(get, data, cursor, detail):
    response = await get("readings/r1/measurements", **cursor)

    assert response.status_code == 422
    assert response.json()["detail"] == detail
    assert data.mock_calls == []


@pytest.mark.asyncio
async def test_buckets_take_bounds_in_utc(get, data):
    response = await get(
        "readings/site 1/measurements/buckets",
        start="2026-01-01T02:00:00+02:00",
        end="2026-01-02T00:00:00Z",
        buckets=300,
    )

    assert response.status_code == 200
    assert data.measurement_buckets.await_args.args == ("site 1",)
    assert data.measurement_buckets.await_args.kwargs == {
        "start": MIDNIGHT,
        "end": datetime(2026, 1, 2, tzinfo=UTC),
        "buckets": 300,
        "view": None,
        "window_ms": None,
    }


@pytest.mark.asyncio
async def test_buckets_without_bounds_ask_for_all_stored_history(get, data):
    response = await get("readings/r1/measurements/buckets")

    assert response.status_code == 200
    assert data.measurement_buckets.await_args.kwargs == {
        "start": None,
        "end": None,
        "buckets": 600,
        "view": None,
        "window_ms": None,
    }


@pytest.mark.asyncio
async def test_an_inverted_range_is_refused(get, data):
    response = await get(
        "readings/r1/measurements/buckets",
        start="2026-01-02T00:00:00Z",
        end="2026-01-01T00:00:00Z",
    )

    assert response.status_code == 422
    assert data.mock_calls == []


@pytest.mark.asyncio
async def test_chart_evidence_names_monitors_and_readings_publicly(get, data):
    response = await get(
        "evidence/chart",
        device_id="pump",
        monitor_id="m1",
        after_created="2026-01-01T01:00:00+01:00",
        after_timestamp="2026-01-01T00:00:00Z",
        after_monitor_id="m0",
        after_sequence_number=4,
        limit=10,
    )

    assert response.status_code == 200
    assert data.chart_evidence.await_args.kwargs == {
        "device_id": "pump",
        "stream_ids": None,
        "service_id": "m1",
        "after_created": MIDNIGHT,
        "after_timestamp": MIDNIGHT,
        "after_service_id": "m0",
        "after_sequence_number": 4,
        "limit": 10,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        pytest.param({}, id="neither"),
        pytest.param({"device_id": "pump", "reading_id": "r1"}, id="both"),
        pytest.param(
            {"reading_id": [f"r{index}" for index in range(201)]}, id="too-many"
        ),
        pytest.param(
            {"reading_id": "r1", "after_created": "2026-01-01T00:00:00Z"},
            id="partial-cursor",
        ),
    ],
)
async def test_chart_evidence_needs_one_scope_and_a_whole_cursor(get, data, params):
    response = await get("evidence/chart", **params)

    assert response.status_code == 422
    assert data.mock_calls == []


@pytest.mark.asyncio
async def test_reading_evidence_asks_for_the_catalogue_reading(get, data):
    response = await get("evidence", reading_id="r1", limit=5)

    assert response.status_code == 200
    assert data.evidence.await_args.args == ("r1",)
    assert data.evidence.await_args.kwargs == {"limit": 5}


@pytest.mark.asyncio
async def test_chart_evidence_of_several_readings_asks_for_each(get, data):
    response = await get("evidence/chart", reading_id=["r1", "r2"], monitor_id="m1")

    assert response.status_code == 200
    asked = data.chart_evidence.await_args.kwargs
    assert (asked["stream_ids"], asked["service_id"], asked["limit"]) == (
        ["r1", "r2"],
        "m1",
        2000,
    )


@pytest.mark.asyncio
async def test_a_profile_looks_back_as_far_as_asked(get, data):
    data.profile.return_value = {
        "reading_id": "stream:1",
        "start": "2026-01-01T00:00:00Z",
        "end": "2026-01-15T00:00:00Z",
        "bucket_seconds": 900,
    }
    response = await get("readings/stream:1/profile")

    assert response.status_code == 200
    assert data.profile.await_args.args == ("stream:1",)
    assert data.profile.await_args.kwargs == {"days": 14}
    # A window without values answers with nulls, not with an error.
    assert response.json()["recent"] is None and response.json()["coverage"] is None
    assert (await get("readings/stream:1/profile", days=90)).status_code == 200
    assert data.profile.await_args.kwargs == {"days": 90}
    for days in (0, 91, "week"):
        refused = await get("readings/stream:1/profile", days=days)
        assert refused.status_code == 422
    assert data.profile.await_count == 2


@pytest.mark.asyncio
async def test_history_display_options_reach_the_buckets(get, data):
    response = await get(
        "readings/r1/measurements/buckets", view="auto", window_ms=15000, buckets=120
    )
    assert response.status_code == 200
    asked = data.measurement_buckets.await_args.kwargs
    assert (asked["buckets"], asked["view"], asked["window_ms"]) == (
        120,
        "auto",
        15000,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params", [{"view": "smooth"}, {"window_ms": 0}, {"window_ms": 86400001}]
)
async def test_invalid_history_display_options_are_refused(get, data, params):
    response = await get("readings/r1/measurements/buckets", **params)
    assert response.status_code == 422
    assert data.mock_calls == []
