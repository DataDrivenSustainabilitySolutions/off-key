"""Use cases for favorite charger operations."""

from sqlalchemy.ext.asyncio import AsyncSession

from off_key_core.config.logs import logger
from off_key_core.db.models import Favorite

from ...domain import ConflictError, InfrastructureError, NotFoundError
from ...repositories import FavoriteRepository


class FavoriteService:
    """Application-level favorite management use cases."""

    def __init__(self, session: AsyncSession, repository: FavoriteRepository):
        self._session = session
        self._repository = repository

    async def list_user_favorites(self, *, user_id: int) -> list[str]:
        favorites = await self._repository.list_by_user_id(user_id=user_id)
        charger_ids = [favorite.charger_id for favorite in favorites]
        logger.info(f"Retrieved {len(charger_ids)} favorites for user {user_id}")
        return charger_ids

    async def add_favorite(self, *, user_id: int, charger_id: str) -> dict[str, str]:
        existing = await self._repository.get(user_id=user_id, charger_id=charger_id)
        if existing is not None:
            raise ConflictError("Charger already favorited")

        favorite = Favorite(user_id=user_id, charger_id=charger_id)

        try:
            await self._repository.add(favorite)
            await self._session.commit()
        except Exception as exc:
            await self._session.rollback()
            raise InfrastructureError(f"Failed to add favorite: {exc}") from exc

        logger.info(f"Added favorite {charger_id} for user {user_id}")
        return {"message": "Favorite added"}

    async def remove_favorite(self, *, user_id: int, charger_id: str) -> dict[str, str]:
        favorite = await self._repository.get(user_id=user_id, charger_id=charger_id)
        if favorite is None:
            raise NotFoundError("Favorite not found")

        try:
            await self._repository.delete(favorite)
            await self._session.commit()
        except Exception as exc:
            await self._session.rollback()
            raise InfrastructureError(f"Failed to remove favorite: {exc}") from exc

        logger.info(f"Removed favorite {charger_id} for user {user_id}")
        return {"message": "Favorite removed"}
