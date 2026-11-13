"""Devices of the catalogue, and the measurements of each reading.

Devices and readings are named by their catalogue ids (`devices[].id`,
`readings[].id` of `GET /v1/catalogue`). The recorded identity behind them is
resolved inside the installation.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from off_key_core.auth.agents import OPEN_TO_AGENTS
from off_key_core.schemas.devices import (
    Device,
    Measurement,
    MeasurementBucket,
    MeasurementPage,
    ReadingProfile,
)
from off_key_core.schemas.system import SystemStream
from off_key_core.utils.timestamps import as_utc

from ...facades.tactic import path_segment, tactic
from ..errors import TacticErrorRoute

router = APIRouter(route_class=TacticErrorRoute)
readings_router = APIRouter(route_class=TacticErrorRoute)


async def data_request(path: str, params: dict[str, Any] | None = None) -> Any:
    return await tactic.request(
        method="GET", endpoint=f"/api/v1/data{path}", params=params
    )


def query_time(value: datetime | None) -> str | None:
    return None if value is None else as_utc(value).isoformat()


def present(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if value is not None}


@router.get("", response_model=list[Device], openapi_extra=OPEN_TO_AGENTS)
async def list_devices(
    active: bool | None = Query(
        None, description="Only devices that are sending data now, or only those not."
    ),
):
    """Catalogue devices with their readings and whether they are sending data."""
    return await data_request("/devices", present({"active": active}))


@router.get(
    "/{device_id}/readings",
    response_model=list[SystemStream],
    openapi_extra=OPEN_TO_AGENTS,
)
async def list_device_readings(device_id: str):
    """The catalogue readings of one device. 404 when the catalogue lacks it."""
    return await data_request(f"/devices/{path_segment(device_id)}/readings")


@readings_router.get(
    "/{reading_id}/measurements",
    response_model=list[Measurement] | MeasurementPage,
    openapi_extra=OPEN_TO_AGENTS,
)
async def list_measurements(
    reading_id: str,
    limit: int = Query(1000, ge=1, le=10000),
    after_timestamp: datetime | None = Query(
        None, description="Page further back in time, before this measurement."
    ),
    after_created: datetime | None = Query(
        None, description="Live cursor: values that arrived after this time."
    ),
    after_event_timestamp: datetime | None = Query(
        None, description="Tie-breaker of the live cursor."
    ),
    paginated: bool = Query(
        False, description="Wrap the values together with the next cursor."
    ),
):
    """Recorded values of one reading.

    Without a cursor the newest values come first, and `after_timestamp` pages
    further back in time. The live cursor `after_created` plus
    `after_event_timestamp` returns values that arrived since, in arrival order.
    """
    if (after_created is None) != (after_event_timestamp is None):
        raise HTTPException(
            status_code=422, detail="All measurement live cursor fields are required"
        )
    if after_timestamp is not None and after_created is not None:
        raise HTTPException(
            status_code=422,
            detail="Historical and live measurement cursors cannot be used together",
        )
    return await data_request(
        f"/readings/{path_segment(reading_id)}/measurements",
        present(
            {
                "limit": limit,
                "after_timestamp": query_time(after_timestamp),
                "after_created": query_time(after_created),
                "after_event_timestamp": query_time(after_event_timestamp),
                "paginated": paginated,
            }
        ),
    )


@readings_router.get(
    "/{reading_id}/measurements/buckets",
    response_model=list[MeasurementBucket],
    openapi_extra=OPEN_TO_AGENTS,
)
async def list_measurement_buckets(
    reading_id: str,
    start: datetime | None = Query(None, description="Omit for all stored history"),
    end: datetime | None = Query(None, description="Defaults to now"),
    buckets: int = Query(600, ge=10, le=2000, description="Time buckets to return"),
):
    """Lowest and highest value per time bucket, so short spikes survive.

    Use it for charts and overviews of long periods.
    """
    if start is not None and end is not None and as_utc(start) >= as_utc(end):
        raise HTTPException(
            status_code=422, detail="Measurement range start must precede its end"
        )
    return await data_request(
        f"/readings/{path_segment(reading_id)}/measurements/buckets",
        present(
            {
                "start": query_time(start),
                "end": query_time(end),
                "buckets": buckets,
            }
        ),
    )


@readings_router.get(
    "/{reading_id}/profile", response_model=ReadingProfile, openapi_extra=OPEN_TO_AGENTS
)
async def profile_reading(
    reading_id: str,
    days: int = Query(14, ge=1, le=90, description="How far back to look."),
):
    """What a reading looks like, so a design can be fitted to it.

    Over the last `days`: when it has values (`first`, `last`, `coverage`,
    `longest_outage_seconds`), how far they reach (`minimum`, `maximum`), how
    much of its variation the hour of the day and the day of the week explain
    (`daily_rhythm`, `weekly_rhythm`, from 0 to 1), and how far its level moved
    (`level_change`). `recent` looks at the newest values, up to 5000 of them:
    the usual `interval_seconds` and the pauses beyond it, mean, `spread` and
    percentiles, the `typical_change` from one value to the next, how long the
    reading stays flat, and its `levels` where it has at most ten. A window
    without values answers with nulls. 404 when the catalogue lacks the reading.
    """
    return await data_request(
        f"/readings/{path_segment(reading_id)}/profile", {"days": days}
    )
