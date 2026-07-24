from fastapi import APIRouter

from ...facades.tactic import TacticError, tactic
from ..errors import raise_tactic_http_error

router = APIRouter()


@router.get("/available", tags=["chargers"])
async def get_all_chargers(skip: int = 0, limit: int = 100):
    try:
        return await tactic.get_chargers(skip=skip, limit=limit, active_only=False)
    except TacticError as e:
        raise_tactic_http_error(e)


@router.get("/active", tags=["chargers"])
async def get_active_chargers(skip: int = 0, limit: int = 100):
    try:
        return await tactic.get_chargers(skip=skip, limit=limit, active_only=True)
    except TacticError as e:
        raise_tactic_http_error(e)


@router.get("/active/id", tags=["chargers"])
async def get_active_charger_ids(skip: int = 0, limit: int = 100):
    try:
        return await tactic.get_active_charger_ids(skip=skip, limit=limit)
    except TacticError as e:
        raise_tactic_http_error(e)
