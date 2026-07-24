from datetime import UTC, datetime

from fastapi import APIRouter, Query

from ...facades.tactic import TacticError, tactic
from ..errors import raise_tactic_http_error

router = APIRouter()


@router.get("/{charger_id}/type")
async def get_telemetry_types_from_id(
    charger_id: str,
    limit: int = Query(
        100, ge=1, le=1000, description="Maximum number of telemetry types to return"
    ),
):
    try:
        return await tactic.get_telemetry_types(charger_id=charger_id, limit=limit)
    except TacticError as e:
        raise_tactic_http_error(e)


@router.get("/{charger_id}/data")
async def get_telemetry(
    charger_id: str,
    telemetry_type: str = Query(..., alias="type"),
    limit: int = 1000,  # Reduced default limit for better performance
    after_timestamp: datetime | None = Query(None),  # Cursor for pagination
    paginated: bool = False,  # Enable paginated response format
):
    # Normalize to UTC to keep cursor behavior stable across clients.
    if after_timestamp is not None:
        after_timestamp = (
            after_timestamp.replace(tzinfo=UTC)
            if after_timestamp.tzinfo is None
            else after_timestamp.astimezone(UTC)
        )

    try:
        return await tactic.get_telemetry_data(
            charger_id=charger_id,
            telemetry_type=telemetry_type,
            limit=limit,
            after_timestamp=after_timestamp,
            paginated=paginated,
        )
    except TacticError as e:
        raise_tactic_http_error(e)
