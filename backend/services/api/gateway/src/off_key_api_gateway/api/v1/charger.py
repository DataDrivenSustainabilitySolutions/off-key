from fastapi import APIRouter

from ...facades.tactic import tactic
from ..errors import TacticErrorRoute

router = APIRouter(route_class=TacticErrorRoute)


@router.get("/available", tags=["chargers"])
async def get_all_chargers(skip: int = 0, limit: int = 100):
    return await tactic.get_chargers(skip=skip, limit=limit, active_only=False)


@router.get("/active", tags=["chargers"])
async def get_active_chargers(skip: int = 0, limit: int = 100):
    return await tactic.get_chargers(skip=skip, limit=limit, active_only=True)


@router.get("/active/id", tags=["chargers"])
async def get_active_charger_ids(skip: int = 0, limit: int = 100):
    return await tactic.get_active_charger_ids(skip=skip, limit=limit)
