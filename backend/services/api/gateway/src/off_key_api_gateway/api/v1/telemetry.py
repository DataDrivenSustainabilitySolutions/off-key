from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx

from off_key_core.db.base import get_db_async
from off_key_core.db.models import Telemetry
from off_key_core.config.config import settings

router = APIRouter()


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
    db: AsyncSession = Depends(get_db_async),
    limit: int = Query(
        100, ge=1, le=1000, description="Maximum number of telemetry types to return"
    ),
):
    stmt = (
        select(Telemetry.type)
        .where(Telemetry.charger_id == charger_id)
        .distinct()
        .order_by(Telemetry.type.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{charger_id}/{telemetry_type}")
async def get_telemetry(
    charger_id: str,
    telemetry_type: str,
    db: AsyncSession = Depends(get_db_async),
    limit: int = 1000,  # Reduced default limit for better performance
    after_timestamp: datetime | None = Query(None),  # Cursor for pagination
    paginated: bool = False,  # Enable paginated response format
):
    query = select(Telemetry).filter(
        Telemetry.charger_id == charger_id, Telemetry.type == telemetry_type
    )

    # Cursor-based pagination for time-series data
    if after_timestamp is not None:
        cursor = (
            after_timestamp.replace(tzinfo=timezone.utc)
            if after_timestamp.tzinfo is None
            else after_timestamp.astimezone(timezone.utc)
        )
        query = query.filter(Telemetry.timestamp < cursor)

    # Always order by timestamp DESC for time-series data
    query = query.order_by(Telemetry.timestamp.desc()).limit(limit)

    result = await db.execute(query)
    results = result.scalars().all()

    # Format results to match frontend expectations exactly
    formatted_results = [
        {"timestamp": str(result.timestamp), "value": result.value}
        for result in results
    ]

    # Return paginated response only if explicitly requested
    if paginated:
        return {
            "data": formatted_results,
            "pagination": {
                "limit": limit,
                "has_more": len(formatted_results) == limit,
                "next_cursor": (
                    formatted_results[-1]["timestamp"] if formatted_results else None
                ),
            },
        }

    # Default: return simple array for backward compatibility
    return formatted_results
