"""Per-observation detector evidence, as the reading charts show it."""

from datetime import datetime

from aberration_core.schemas.devices import ChartEvidence, Evidence
from fastapi import APIRouter, HTTPException, Query, Request

from ..errors import TacticErrorRoute
from ..rate_limiter import limiter
from .devices import data_request, present, query_time

router = APIRouter(route_class=TacticErrorRoute)
MAX_CHART_READINGS = 200
shared_limit_fetch = limiter.shared_limit("60/minute", scope="services")


@router.get("", response_model=list[Evidence])
@shared_limit_fetch
async def list_evidence(
    request: Request,
    reading_id: str = Query(description="Catalogue reading id."),
    limit: int = Query(default=2000, ge=1, le=10000),
):
    """Detector evidence of the newest monitor observations that covered one
    reading, oldest first: scores, calibrated p-values and the accumulated
    evidence behind alarms.
    """
    return await data_request("/evidence", {"stream_id": reading_id, "limit": limit})


@router.get("/chart", response_model=list[ChartEvidence])
@shared_limit_fetch
async def list_chart_evidence(
    request: Request,
    device_id: str | None = Query(
        default=None, description="Evidence of every reading of this device."
    ),
    reading_id: list[str] | None = Query(
        default=None,
        description="Evidence that covered any of these readings; repeat the field.",
    ),
    monitor_id: str | None = Query(default=None, min_length=1, max_length=128),
    after_created: datetime | None = None,
    after_timestamp: datetime | None = None,
    after_monitor_id: str | None = None,
    after_sequence_number: int | None = Query(default=None, ge=1),
    limit: int = Query(default=2000, ge=1, le=10000),
):
    """What reading charts draw for monitor observations, oldest first when
    paging forward.

    Name either `device_id` or one or more `reading_id`, and optionally one
    monitor. Page with the four `after_*` fields together, taken from the last
    row of the previous page.
    """
    if (device_id is None) == (not reading_id):
        raise HTTPException(
            status_code=422, detail="Name either device_id or reading_id"
        )
    if reading_id and len(reading_id) > MAX_CHART_READINGS:
        raise HTTPException(
            status_code=422,
            detail=f"Name at most {MAX_CHART_READINGS} readings",
        )
    cursor = (after_created, after_timestamp, after_monitor_id, after_sequence_number)
    if any(value is not None for value in cursor) and not all(
        value is not None for value in cursor
    ):
        raise HTTPException(
            status_code=422,
            detail="All monitoring evidence cursor fields are required together",
        )
    return await data_request(
        "/evidence/chart",
        present(
            {
                "device_id": device_id,
                "stream_id": reading_id,
                "service_id": monitor_id,
                "after_created": query_time(after_created),
                "after_timestamp": query_time(after_timestamp),
                "after_service_id": after_monitor_id,
                "after_sequence_number": after_sequence_number,
                "limit": limit,
            }
        ),
    )
