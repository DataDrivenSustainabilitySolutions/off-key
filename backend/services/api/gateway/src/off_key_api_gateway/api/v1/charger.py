from fastapi import APIRouter, HTTPException
import httpx

from off_key_core.config.config import settings
from ...facades.tactic import tactic

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
async def get_all_chargers(skip: int = 0, limit: int = 100):
    """Get all available chargers via TACTIC data service."""
    try:
        return await tactic.get_chargers(skip=skip, limit=limit, active_only=False)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve chargers: {str(e)}"
        )


@router.get("/active", tags=["chargers"])
async def get_active_chargers(skip: int = 0, limit: int = 100):
    """Get active chargers via TACTIC data service."""
    try:
        return await tactic.get_chargers(skip=skip, limit=limit, active_only=True)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve active chargers: {str(e)}"
        )


@router.get("/active/id", tags=["chargers"])
async def get_active_charger_ids(skip: int = 0, limit: int = 100):
    """Get active charger IDs via TACTIC data service."""
    try:
        return await tactic.get_active_charger_ids(skip=skip, limit=limit)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve active charger IDs: {str(e)}"
        )
