from fastapi import APIRouter

from ...facades.tactic import tactic
from ..errors import TacticErrorRoute

router = APIRouter(route_class=TacticErrorRoute)


@router.get("/available", tags=["chargers"])
async def list_entities(skip: int = 0, limit: int = 100):
    """Recorded entities with their connection state, paged by `skip` and `limit`.

    An entity is what telemetry, evidence and alarms call `charger_id`.
    """
    return await tactic.get_chargers(skip=skip, limit=limit, active_only=False)


@router.get("/active", tags=["chargers"])
async def list_active_entities(skip: int = 0, limit: int = 100):
    """Recorded entities that are currently online, paged by `skip` and `limit`."""
    return await tactic.get_chargers(skip=skip, limit=limit, active_only=True)


@router.get("/active/id", tags=["chargers"])
async def list_active_entity_ids(skip: int = 0, limit: int = 100):
    """Only the ids of entities that are currently online."""
    return await tactic.get_active_charger_ids(skip=skip, limit=limit)
