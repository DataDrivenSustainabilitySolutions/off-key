from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from off_key_core.db.base import get_db_async
from off_key_core.db.models import Charger
from ...services.chargers import ChargersSyncService
from ...provider import get_chargers_sync_service

router = APIRouter()


@router.post("/sync", tags=["chargers"])
async def sync_chargers(
    service: ChargersSyncService = Depends(get_chargers_sync_service),
):
    await service.sync_chargers()
    return {"status": "successful"}


@router.post("/clean", tags=["chargers"])
async def clean_chargers(
    older_n_days: int,
    service: ChargersSyncService = Depends(get_chargers_sync_service),
):
    await service.clean_chargers(days_inactive=older_n_days)
    return {"status": "successful"}


@router.get("/available", tags=["chargers"])
async def get_all_chargers(
    skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db_async)
):
    query = select(Charger).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/active", tags=["chargers"])
async def get_active_chargers(
    skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db_async)
):
    query = select(Charger).filter(Charger.online).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/active/id", tags=["chargers"])
async def get_active_charger_ids(
    skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db_async)
):
    query = select(Charger.charger_id).filter(Charger.online).offset(skip).limit(limit)
    result = await db.execute(query)
    active_ids = result.scalars().all()
    return {"active": list(active_ids)}
