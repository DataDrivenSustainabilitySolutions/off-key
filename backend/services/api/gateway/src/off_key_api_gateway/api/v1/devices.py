"""Devices of the catalogue, and the measurements of each reading.

Devices and readings are named by their catalogue ids (`devices[].id`,
`readings[].id` of `GET /v1/catalogue`). The recorded identity behind them is
resolved here, against the saved catalogue.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from off_key_core.auth.agents import OPEN_TO_AGENTS
from off_key_core.schemas.devices import (
    Device,
    Measurement,
    MeasurementBucket,
    MeasurementHistory,
    MeasurementPage,
    ReadingProfile,
)
from off_key_core.schemas.system import SystemStream
from off_key_core.utils.timestamps import as_utc
from off_key_tactic_middleware.services.data import CatalogueDataService

from ...providers import get_catalogue_data_service
from ..errors import DomainErrorRoute

router = APIRouter(route_class=DomainErrorRoute)
readings_router = APIRouter(route_class=DomainErrorRoute)


def utc(value: datetime | None) -> datetime | None:
    """A query time without a zone is UTC."""
    return None if value is None else as_utc(value)


@router.get("", response_model=list[Device], openapi_extra=OPEN_TO_AGENTS)
async def list_devices(
    active: bool | None = Query(
        None, description="Only devices that are sending data now, or only those not."
    ),
    service: CatalogueDataService = Depends(get_catalogue_data_service),
):
    """Catalogue devices with their readings and whether they are sending data."""
    return await service.devices(active=active)


@router.get(
    "/{device_id}/readings",
    response_model=list[SystemStream],
    openapi_extra=OPEN_TO_AGENTS,
)
async def list_device_readings(
    device_id: str,
    service: CatalogueDataService = Depends(get_catalogue_data_service),
):
    """The catalogue readings of one device. 404 when the catalogue lacks it."""
    return service.device_readings(device_id)


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
    service: CatalogueDataService = Depends(get_catalogue_data_service),
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
    return await service.measurements(
        reading_id,
        limit=limit,
        after_timestamp=utc(after_timestamp),
        after_created=utc(after_created),
        after_event_timestamp=utc(after_event_timestamp),
        paginated=paginated,
    )


@readings_router.get(
    "/{reading_id}/measurements/buckets",
    response_model=list[MeasurementBucket] | MeasurementHistory,
    openapi_extra=OPEN_TO_AGENTS,
)
async def list_measurement_buckets(
    reading_id: str,
    start: datetime | None = Query(None, description="Omit for all stored history"),
    end: datetime | None = Query(None, description="Defaults to now"),
    buckets: int = Query(600, ge=10, le=2000, description="Time buckets to return"),
    view: Literal["auto", "raw"] | None = Query(
        None,
        description="Auto returns means with min/max/count for dense ranges, "
        "original samples for sparse ranges. Raw returns up to the latest "
        "10,000 original samples with an explicit truncation flag.",
    ),
    window_ms: int | None = Query(
        None,
        ge=1,
        le=86_400_000,
        description="Minimum averaging interval in milliseconds; wider ranges "
        "may use a coarser interval.",
    ),
    service: CatalogueDataService = Depends(get_catalogue_data_service),
):
    """Lowest and highest value per time bucket, so short spikes survive.

    Use it for charts and overviews of long periods.
    """
    if start is not None and end is not None and as_utc(start) >= as_utc(end):
        raise HTTPException(
            status_code=422, detail="Measurement range start must precede its end"
        )
    return await service.measurement_buckets(
        reading_id,
        start=utc(start),
        end=utc(end),
        buckets=buckets,
        view=view,
        window_ms=window_ms,
    )


@readings_router.get(
    "/{reading_id}/profile", response_model=ReadingProfile, openapi_extra=OPEN_TO_AGENTS
)
async def profile_reading(
    reading_id: str,
    days: int = Query(14, ge=1, le=90, description="How far back to look."),
    service: CatalogueDataService = Depends(get_catalogue_data_service),
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
    return await service.profile(reading_id, days=days)
