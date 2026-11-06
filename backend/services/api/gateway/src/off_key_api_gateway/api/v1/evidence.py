"""Per-observation detector evidence, as the reading charts show it."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from off_key_core.utils.timestamps import as_utc

from ...facades.tactic import tactic
from ..errors import TacticErrorRoute
from ..rate_limiter import limiter

router = APIRouter(route_class=TacticErrorRoute)
shared_limit_fetch = limiter.shared_limit("60/minute", scope="services")


@router.get("", response_model=list[dict[str, Any]])
@shared_limit_fetch
async def list_evidence(
    request: Request,
    charger_id: str,
    telemetry_type: str | None = None,
    limit: int = Query(default=2000, ge=1, le=10000),
):
    """Per-observation detector evidence of one entity, newest first.

    Scores, calibrated p-values and the accumulated evidence behind alarms,
    optionally for one telemetry type.
    """
    return await tactic.get_monitoring_evidence(
        charger_id=charger_id,
        telemetry_type=telemetry_type,
        limit=limit,
    )


@router.get("/chart", response_model=list[dict[str, Any]])
@shared_limit_fetch
async def list_chart_evidence(
    request: Request,
    charger_id: str,
    service_id: str | None = Query(default=None, min_length=1, max_length=128),
    after_created: datetime | None = None,
    after_timestamp: datetime | None = None,
    after_service_id: str | None = None,
    after_sequence_number: int | None = Query(default=None, ge=1),
    limit: int = Query(default=2000, ge=1, le=10000),
):
    """Detector evidence of one entity for charts, optionally for one monitor.

    Page with the four `after_*` cursor fields together, taken from the last
    row of the previous page.
    """
    cursor_values = (
        after_created,
        after_timestamp,
        after_service_id,
        after_sequence_number,
    )
    if any(value is not None for value in cursor_values) and not all(
        value is not None for value in cursor_values
    ):
        raise HTTPException(
            status_code=422,
            detail="All monitoring evidence cursor fields are required together",
        )
    if after_created is not None:
        after_created = as_utc(after_created)
    if after_timestamp is not None:
        after_timestamp = as_utc(after_timestamp)
    return await tactic.get_monitoring_chart_evidence(
        charger_id=charger_id,
        service_id=service_id,
        after_created=after_created,
        after_timestamp=after_timestamp,
        after_service_id=after_service_id,
        after_sequence_number=after_sequence_number,
        limit=limit,
    )
