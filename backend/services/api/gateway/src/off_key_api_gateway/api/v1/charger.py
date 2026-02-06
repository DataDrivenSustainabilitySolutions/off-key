from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx

from off_key_core.db.base import get_db_async
from off_key_core.db.models import Charger
from off_key_core.config.config import get_settings

settings = get_settings()

router = APIRouter()


@router.post("/sync", tags=["chargers"])
async def sync_chargers():
    """Trigger manual charger sync via db-sync service."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.db_sync_service_url}/sync/chargers",
                timeout=300.0,  # 5 minute timeout for sync operation
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to trigger charger sync: {str(e)}"
        )


@router.post("/clean", tags=["chargers"])
async def clean_chargers(older_n_days: int):
    """Trigger manual charger cleanup via db-sync service."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.db_sync_service_url}/sync/chargers/clean",
                params={"days_inactive": older_n_days},
                timeout=300.0,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to trigger charger cleanup: {str(e)}"
        )


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
