from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ...db.base import get_db_async
from ...db.models import Charger
from ...services.chargers import ChargersSyncService

router = APIRouter()


@router.post("/sync", tags=["chargers"])
async def sync_chargers(db: AsyncSession = Depends(get_db_async)):
    service = ChargersSyncService(db)
    await service.sync_chargers()
    return {"status": "successful"}


@router.post("/clean", tags=["chargers"])
async def clean_chargers(older_n_days: int, db: AsyncSession = Depends(get_db_async)):
    service = ChargersSyncService(db)
    await service.clean_chargers(days_inactive=older_n_days)
    return {"status": "successful"}


@router.get("/available", tags=["chargers"])
async def get_all_chargers(db: AsyncSession = Depends(get_db_async)):
    result = await db.execute(select(Charger))
    return result.scalars().all()


@router.get("/active", tags=["chargers"])
async def get_active_chargers(db: AsyncSession = Depends(get_db_async)):
    result = await db.execute(select(Charger).filter(Charger.online))
    return result.scalars().all()


@router.get("/active/id", tags=["chargers"])
async def get_active_charger_ids(db: AsyncSession = Depends(get_db_async)):
    result = await db.execute(select(Charger.charger_id).filter(Charger.online))
    active_ids = result.scalars().all()
    return {"active": list(active_ids)}
