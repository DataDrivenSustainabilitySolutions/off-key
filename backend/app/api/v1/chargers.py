from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ...db.base import get_db_sync, get_db_async
from ...db.models import Chargers
from ...services.chargers_sync import ChargersSyncService

router = APIRouter()


@router.post("/sync", tags=["chargers"])
async def sync_chargers(db: AsyncSession = Depends(get_db_async)):
    service = ChargersSyncService(db)
    await service.sync_chargers()
    return {"status": "successful"}


@router.get("/active", tags=["chargers"])
def get_active_chargers(db: Session = Depends(get_db_sync)):
    return db.query(Chargers).filter(Chargers.online).all()


@router.get("/active/id", tags=["chargers"])
def get_active_charger_ids(db: Session = Depends(get_db_sync)):
    active_ids = db.query(Chargers.charger_id).filter(Chargers.online).all()
    return {"active": [active_id[0] for active_id in active_ids]}
