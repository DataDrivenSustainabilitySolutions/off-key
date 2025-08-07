from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ...db.base import get_db_async
from ...db.models import Telemetry
from ...services.telemetry import TelemetrySyncService
from ...core.dependencies import get_charger_api_client
from ...core.client.base_client import ChargerAPIClient

router = APIRouter()


@router.post("/sync")
async def sync_chargers(
    db: AsyncSession = Depends(get_db_async),
    client: ChargerAPIClient = Depends(get_charger_api_client),
    limit: int = 10_000,
):
    service = TelemetrySyncService(db, client)
    await service.sync_telemetry(limit=limit)
    return {"status": "successful"}


@router.get("/{charger_id}/type")
async def get_telemetry_types_from_id(
    charger_id: str, db: AsyncSession = Depends(get_db_async)
):
    result = await db.execute(
        select(Telemetry.type).filter(Telemetry.charger_id == charger_id).distinct()
    )
    return result.scalars().all()


@router.get("/{charger_id}/{telemetry_type}")
async def get_telemetry(
    charger_id: str,
    telemetry_type: str,
    db: AsyncSession = Depends(get_db_async),
    limit: int = 1000,  # Reduced default limit for better performance
    after_timestamp: str = None,  # Cursor for pagination
    paginated: bool = False,  # Enable paginated response format
):
    query = select(Telemetry).filter(
        Telemetry.charger_id == charger_id, Telemetry.type == telemetry_type
    )

    # Cursor-based pagination for time-series data
    if after_timestamp:
        query = query.filter(Telemetry.timestamp < after_timestamp)

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
