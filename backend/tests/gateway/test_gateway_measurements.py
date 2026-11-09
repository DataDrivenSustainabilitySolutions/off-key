"""Device, measurement and evidence reads validate their input and forward
catalogue ids to TACTIC, with times in UTC."""

from unittest.mock import AsyncMock

import pytest
from aberration_api_gateway.api.rate_limiter import limiter
from aberration_api_gateway.facades import tactic as facade

from tests.support.gateway import gateway_app, member_profile
from tests.support.http import asgi_client


@pytest.fixture
def remote(monkeypatch):
    request = AsyncMock(return_value=[])
    monkeypatch.setattr(facade.tactic, "request", request)
    yield request
    limiter.reset()


async def get(path, **params):
    async with asgi_client(gateway_app(member_profile())) as client:
        return await client.get(f"/v1/{path}", params=params)


@pytest.mark.asyncio
async def test_devices_forward_the_activity_filter_only_when_given(remote):
    assert (await get("devices")).status_code == 200
    assert remote.await_args.kwargs == {
        "method": "GET",
        "endpoint": "/api/v1/data/devices",
        "params": {},
    }
    assert (await get("devices", active="true")).status_code == 200
    assert remote.await_args.kwargs["params"] == {"active": True}


@pytest.mark.asyncio
async def test_device_readings_address_an_encoded_device(remote):
    response = await get("devices/site 1/readings")

    assert response.status_code == 200
    assert remote.await_args.kwargs["endpoint"] == (
        "/api/v1/data/devices/site%201/readings"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cursor", "forwarded"),
    [
        pytest.param({}, {}, id="first-page"),
        pytest.param(
            {"after_timestamp": "2026-01-01T02:00:00+02:00"},
            {"after_timestamp": "2026-01-01T00:00:00+00:00"},
            id="history",
        ),
        pytest.param(
            {
                "after_created": "2026-01-01T01:00:00+01:00",
                "after_event_timestamp": "2025-12-31T19:00:00-05:00",
            },
            {
                "after_created": "2026-01-01T00:00:00+00:00",
                "after_event_timestamp": "2026-01-01T00:00:00+00:00",
            },
            id="live",
        ),
    ],
)
async def test_measurement_cursors_are_forwarded_in_utc(remote, cursor, forwarded):
    response = await get(
        "readings/stream:1/measurements", limit=50, paginated="true", **cursor
    )

    assert response.status_code == 200
    assert remote.await_args.kwargs == {
        "method": "GET",
        "endpoint": "/api/v1/data/readings/stream%3A1/measurements",
        "params": {"limit": 50, "paginated": True} | forwarded,
    }


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
async def test_inconsistent_cursors_are_rejected_before_tactic(remote, cursor, detail):
    response = await get("readings/r1/measurements", **cursor)

    assert response.status_code == 422
    assert response.json()["detail"] == detail
    remote.assert_not_awaited()


@pytest.mark.asyncio
async def test_buckets_forward_bounds_in_utc(remote):
    response = await get(
        "readings/site 1/measurements/buckets",
        start="2026-01-01T02:00:00+02:00",
        end="2026-01-02T00:00:00Z",
        buckets=300,
    )

    assert response.status_code == 200
    assert remote.await_args.kwargs == {
        "method": "GET",
        "endpoint": "/api/v1/data/readings/site%201/measurements/buckets",
        "params": {
            "buckets": 300,
            "start": "2026-01-01T00:00:00+00:00",
            "end": "2026-01-02T00:00:00+00:00",
        },
    }


@pytest.mark.asyncio
async def test_buckets_without_bounds_ask_for_all_stored_history(remote):
    response = await get("readings/r1/measurements/buckets")

    assert response.status_code == 200
    assert remote.await_args.kwargs["params"] == {"buckets": 600}


@pytest.mark.asyncio
async def test_inverted_range_is_rejected_before_tactic(remote):
    response = await get(
        "readings/r1/measurements/buckets",
        start="2026-01-02T00:00:00Z",
        end="2026-01-01T00:00:00Z",
    )

    assert response.status_code == 422
    remote.assert_not_awaited()


@pytest.mark.asyncio
async def test_chart_evidence_names_monitors_and_readings_publicly(remote):
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
    assert remote.await_args.kwargs == {
        "method": "GET",
        "endpoint": "/api/v1/data/evidence/chart",
        "params": {
            "device_id": "pump",
            "service_id": "m1",
            "after_created": "2026-01-01T00:00:00+00:00",
            "after_timestamp": "2026-01-01T00:00:00+00:00",
            "after_service_id": "m0",
            "after_sequence_number": 4,
            "limit": 10,
        },
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
async def test_chart_evidence_needs_one_scope_and_a_whole_cursor(remote, params):
    response = await get("evidence/chart", **params)

    assert response.status_code == 422
    remote.assert_not_awaited()


@pytest.mark.asyncio
async def test_reading_evidence_forwards_the_catalogue_reading(remote):
    response = await get("evidence", reading_id="r1", limit=5)

    assert response.status_code == 200
    assert remote.await_args.kwargs == {
        "method": "GET",
        "endpoint": "/api/v1/data/evidence",
        "params": {"stream_id": "r1", "limit": 5},
    }


@pytest.mark.asyncio
async def test_chart_evidence_of_several_readings_forwards_each(remote):
    response = await get("evidence/chart", reading_id=["r1", "r2"], monitor_id="m1")

    assert response.status_code == 200
    assert remote.await_args.kwargs["params"] == {
        "stream_id": ["r1", "r2"],
        "service_id": "m1",
        "limit": 2000,
    }
