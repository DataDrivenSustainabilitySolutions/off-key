from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status
import httpx

from off_key_core.config.config import get_settings
from ...facades.tactic import TacticError, tactic

settings = get_settings()

router = APIRouter()


def _get_tactic_error_detail(error: TacticError) -> str:
    """Extract API detail from TACTIC error body when available."""
    if isinstance(error.body, dict):
        detail = error.body.get("detail")
        if detail:
            return str(detail)
    return str(error)


def _raise_tactic_http_error(error: TacticError) -> None:
    raise HTTPException(
        status_code=error.status or status.HTTP_502_BAD_GATEWAY,
        detail=_get_tactic_error_detail(error),
    )


@router.post("/sync")
async def sync_telemetry(limit: int = 10_000):
    """Trigger manual telemetry sync via db-sync service."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.db_sync_service_url}/sync/telemetry",
                params={"limit": limit},
                timeout=600.0,  # 10 minute timeout for telemetry sync
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to trigger telemetry sync: {str(e)}"
        )


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
        _raise_tactic_http_error(e)


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
            after_timestamp.replace(tzinfo=timezone.utc)
            if after_timestamp.tzinfo is None
            else after_timestamp.astimezone(timezone.utc)
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
        _raise_tactic_http_error(e)
