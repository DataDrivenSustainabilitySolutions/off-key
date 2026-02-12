"""Use cases for charger data queries."""

from off_key_core.config.logs import logger
from off_key_core.db.models import Charger

from ...repositories import ChargerRepository


class ChargerQueryService:
    """Application-level charger query use cases."""

    def __init__(self, repository: ChargerRepository):
        self._repository = repository

    async def list_chargers(
        self,
        *,
        skip: int,
        limit: int,
        active_only: bool,
    ) -> list[Charger]:
        chargers = await self._repository.list_chargers(
            skip=skip,
            limit=limit,
            active_only=active_only,
        )
        logger.info(f"Retrieved {len(chargers)} chargers (active_only={active_only})")
        return chargers

    async def list_active_charger_ids(
        self, *, skip: int, limit: int
    ) -> dict[str, list[str]]:
        active_ids = await self._repository.list_active_charger_ids(
            skip=skip, limit=limit
        )
        return {"active": active_ids}
