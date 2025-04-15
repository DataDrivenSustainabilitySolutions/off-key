from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.base import get_db_sync, get_db_async
from ...db.models import Telemetry
from ...services.telemetry import TelemetrySyncService

router = APIRouter()


@router.post("/sync")
async def sync_chargers(db: AsyncSession = Depends(get_db_async), limit: int = 10_000):
    service = TelemetrySyncService(db)
    await service.sync_telemetry(limit=limit)
    return {"status": "successful"}


@router.get("/{charger_id}/type")
def get_telemetry_types_from_id(charger_id: str, db: Session = Depends(get_db_sync)):
    charger_types = (
        db.query(Telemetry.type)
        .filter(Telemetry.charger_id == charger_id)
        .distinct()
        .all()
    )
    return [charger_type[0] for charger_type in charger_types]


@router.get("/{charger_id}/{telemetry_type}")
def get_telemetry(
    charger_id: str,
    telemetry_type: str,
    db: Session = Depends(get_db_sync),
    limit: int = 10_000,
):
    query = db.query(Telemetry).filter(
        Telemetry.charger_id == charger_id, Telemetry.type == telemetry_type
    )

    if limit:
        query = query.order_by(Telemetry.timestamp.desc()).limit(limit)

    results = query.all()
    formatted_results = [
        {"timestamp": result.timestamp, "value": result.value} for result in results
    ]

    return formatted_results
