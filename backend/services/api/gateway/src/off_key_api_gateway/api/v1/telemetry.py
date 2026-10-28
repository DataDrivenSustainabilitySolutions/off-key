from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from off_key_core.utils.timestamps import as_utc

from ...facades.tactic import tactic
from ..errors import TacticErrorRoute

router = APIRouter(route_class=TacticErrorRoute)


@router.get("/{charger_id}/type")
async def get_telemetry_types_from_id(
    charger_id: str,
    limit: int = Query(
        100, ge=1, le=1000, description="Maximum number of telemetry types to return"
    ),
):
    return await tactic.get_telemetry_types(charger_id=charger_id, limit=limit)


@router.get("/{charger_id}/data")
async def get_telemetry(
    charger_id: str,
    telemetry_type: str = Query(..., alias="type"),
    limit: int = 1000,  # Reduced default limit for better performance
    after_timestamp: datetime | None = Query(None),  # Cursor for pagination
    after_created: datetime | None = Query(None),  # Live ingestion cursor
    after_event_timestamp: datetime | None = Query(None),  # Cursor tie-breaker
    paginated: bool = False,  # Enable paginated response format
):
    cursor_values = (after_created, after_event_timestamp)
    if any(value is not None for value in cursor_values) and not all(
        value is not None for value in cursor_values
    ):
        raise HTTPException(
            status_code=422,
            detail="All telemetry live cursor fields are required",
        )
    if after_timestamp is not None and after_created is not None:
        raise HTTPException(
            status_code=422,
            detail="Historical and live telemetry cursors cannot be used together",
        )

    # Normalize to UTC to keep cursor behavior stable across clients.
    if after_timestamp is not None:
        after_timestamp = as_utc(after_timestamp)
    if after_created is not None:
        after_created = as_utc(after_created)
    if after_event_timestamp is not None:
        after_event_timestamp = as_utc(after_event_timestamp)

    return await tactic.get_telemetry_data(
        charger_id=charger_id,
        telemetry_type=telemetry_type,
        limit=limit,
        after_timestamp=after_timestamp,
        after_created=after_created,
        after_event_timestamp=after_event_timestamp,
        paginated=paginated,
    )


@router.get("/{charger_id}/range")
async def get_telemetry_range(
    charger_id: str,
    telemetry_type: str = Query(..., alias="type"),
    start: datetime | None = Query(None, description="Omit for all stored history"),
    end: datetime | None = Query(None, description="Defaults to now"),
    buckets: int = Query(600, ge=10, le=2000, description="Time buckets to return"),
):
    """Return each bucket's lowest and highest value, so spikes survive."""
    if start is not None and end is not None and as_utc(start) >= as_utc(end):
        raise HTTPException(
            status_code=422, detail="Telemetry range start must precede its end"
        )
    return await tactic.get_telemetry_range(
        charger_id=charger_id,
        telemetry_type=telemetry_type,
        start=as_utc(start) if start is not None else None,
        end=as_utc(end) if end is not None else None,
        buckets=buckets,
    )
