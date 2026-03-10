from fastapi import APIRouter, HTTPException, status
import httpx

from off_key_core.config.services import get_service_endpoints_settings
from ...facades.tactic import TacticError, tactic

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


@router.post("/sync", tags=["chargers"])
async def sync_chargers():
    """Trigger manual charger sync via db-sync service."""
    service_endpoints = get_service_endpoints_settings()
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{service_endpoints.db_sync_service_url}/sync/chargers",
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
    service_endpoints = get_service_endpoints_settings()
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{service_endpoints.db_sync_service_url}/sync/chargers/clean",
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
    try:
        return await tactic.get_chargers(skip=skip, limit=limit, active_only=False)
    except TacticError as e:
        _raise_tactic_http_error(e)


@router.get("/active", tags=["chargers"])
async def get_active_chargers(skip: int = 0, limit: int = 100):
    try:
        return await tactic.get_chargers(skip=skip, limit=limit, active_only=True)
    except TacticError as e:
        _raise_tactic_http_error(e)


@router.get("/active/id", tags=["chargers"])
async def get_active_charger_ids(skip: int = 0, limit: int = 100):
    try:
        return await tactic.get_active_charger_ids(skip=skip, limit=limit)
    except TacticError as e:
        _raise_tactic_http_error(e)
