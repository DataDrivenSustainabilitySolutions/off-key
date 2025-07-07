from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ...db.base import get_db_async
from ...db.models import Telemetry
from ...services.telemetry import TelemetrySyncService

router = APIRouter()


@router.post("/sync")
async def sync_chargers(db: AsyncSession = Depends(get_db_async), limit: int = 10_000):
    service = TelemetrySyncService(db)
    await service.sync_telemetry(limit=limit)
    return {"status": "successful"}


@router.get("/{charger_id}/type")
async def get_telemetry_types_from_id(charger_id: str, db: AsyncSession = Depends(get_db_async)):
    result = await db.execute(
        select(Telemetry.type)
        .filter(Telemetry.charger_id == charger_id)
        .distinct()
    )
    return result.scalars().all()


@router.get("/{charger_id}/{telemetry_type}")
async def get_telemetry(
    charger_id: str,
    telemetry_type: str,
    db: AsyncSession = Depends(get_db_async),
    limit: int = 10_000,
):
    query = select(Telemetry).filter(
        Telemetry.charger_id == charger_id, Telemetry.type == telemetry_type
    )

    if limit:
        query = query.order_by(Telemetry.timestamp.desc()).limit(limit)

    result = await db.execute(query)
    results = result.scalars().all()
    formatted_results = [
        {"timestamp": result.timestamp, "value": result.value} for result in results
    ]

    return formatted_results
