"""Devices, measurements and evidence addressed by catalogue id.

The recorded identity behind a device or reading is resolved here, against the
saved catalogue, so callers name only catalogue ids.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from off_key_core.schemas.devices import (
    ChartEvidence,
    Device,
    Evidence,
    Measurement,
    MeasurementBucket,
    MeasurementHistory,
    MeasurementPage,
    ReadingProfile,
)
from off_key_core.schemas.system import SystemStream

from ...domain import ValidationError
from ...provider import get_catalogue_data_service
from ...services.data import CatalogueDataService
from ..errors import DomainErrorRoute

router = APIRouter(route_class=DomainErrorRoute)


@router.get("/devices", response_model=list[Device])
async def list_devices(
    active: bool | None = Query(None),
    service: CatalogueDataService = Depends(get_catalogue_data_service),
):
    return await service.devices(active=active)


@router.get("/devices/{device_id}/readings", response_model=list[SystemStream])
async def list_device_readings(
    device_id: str,
    service: CatalogueDataService = Depends(get_catalogue_data_service),
):
    return service.device_readings(device_id)


@router.get(
    "/readings/{stream_id}/measurements",
    response_model=list[Measurement] | MeasurementPage,
)
async def list_measurements(
    stream_id: str,
    limit: int = Query(1000, ge=1, le=10000),
    after_timestamp: datetime | None = Query(None),
    after_created: datetime | None = Query(None),
    after_event_timestamp: datetime | None = Query(None),
    paginated: bool = Query(False),
    service: CatalogueDataService = Depends(get_catalogue_data_service),
):
    if (after_created is None) != (after_event_timestamp is None):
        raise ValidationError("All measurement live cursor fields are required")
    if after_timestamp is not None and after_created is not None:
        raise ValidationError(
            "Historical and live measurement cursors cannot be used together"
        )
    return await service.measurements(
        stream_id,
        limit=limit,
        after_timestamp=after_timestamp,
        after_created=after_created,
        after_event_timestamp=after_event_timestamp,
        paginated=paginated,
    )


@router.get(
    "/readings/{stream_id}/measurements/buckets",
    response_model=list[MeasurementBucket] | MeasurementHistory,
)
async def list_measurement_buckets(
    stream_id: str,
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    buckets: int = Query(600, ge=10, le=2000),
    view: Literal["auto", "raw"] | None = Query(None),
    window_ms: int | None = Query(None, ge=1, le=86_400_000),
    service: CatalogueDataService = Depends(get_catalogue_data_service),
):
    return await service.measurement_buckets(
        stream_id, start=start, end=end, buckets=buckets, view=view, window_ms=window_ms
    )


@router.get("/readings/{stream_id}/profile", response_model=ReadingProfile)
async def profile_reading(
    stream_id: str,
    days: int = Query(14, ge=1, le=90),
    service: CatalogueDataService = Depends(get_catalogue_data_service),
):
    return await service.profile(stream_id, days=days)


@router.get("/evidence", response_model=list[Evidence])
async def list_evidence(
    stream_id: str,
    limit: int = Query(2000, ge=1, le=10000),
    service: CatalogueDataService = Depends(get_catalogue_data_service),
):
    return await service.evidence(stream_id, limit=limit)


@router.get("/evidence/chart", response_model=list[ChartEvidence])
async def list_chart_evidence(
    device_id: str | None = Query(None),
    stream_id: list[str] | None = Query(None),
    service_id: str | None = Query(None, min_length=1, max_length=128),
    after_created: datetime | None = Query(None),
    after_timestamp: datetime | None = Query(None),
    after_service_id: str | None = Query(None),
    after_sequence_number: int | None = Query(None, ge=1),
    limit: int = Query(2000, ge=1, le=10000),
    service: CatalogueDataService = Depends(get_catalogue_data_service),
):
    cursor = (after_created, after_timestamp, after_service_id, after_sequence_number)
    if any(value is not None for value in cursor) and not all(
        value is not None for value in cursor
    ):
        raise ValidationError(
            "All monitoring evidence cursor fields are required together"
        )
    return await service.chart_evidence(
        device_id=device_id,
        stream_ids=stream_id,
        service_id=service_id,
        after_created=after_created,
        after_timestamp=after_timestamp,
        after_service_id=after_service_id,
        after_sequence_number=after_sequence_number,
        limit=limit,
    )
