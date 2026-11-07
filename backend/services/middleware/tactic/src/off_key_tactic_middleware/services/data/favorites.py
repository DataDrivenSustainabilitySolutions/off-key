"""Use cases for the favorites each member keeps."""

from off_key_core.config.logs import logger
from off_key_core.db.models import User
from off_key_core.schemas.favorites import (
    MAX_FAVORITES,
    Favorite,
    FavoriteKind,
    FavoriteRef,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain import ConflictError, InfrastructureError
from ...repositories import FavoriteRepository


def _favorite(row) -> Favorite:
    return Favorite(kind=row.kind, id=row.item_id, created_at=row.created_at)


class FavoriteService:
    """Add, list and remove favorites. Adding and removing are idempotent."""

    def __init__(self, session: AsyncSession, repository: FavoriteRepository):
        self._session = session
        self._repository = repository

    async def list_favorites(
        self, *, user_id: int, kind: FavoriteKind | None = None
    ) -> list[Favorite]:
        rows = await self._repository.list(user_id=user_id, kind=kind)
        return [_favorite(row) for row in rows]

    async def add_favorite(self, *, user_id: int, ref: FavoriteRef) -> Favorite:
        # Serialize additions for this member through the count and commit.
        await self._session.execute(
            select(User.id).where(User.id == user_id).with_for_update()
        )
        key = {"user_id": user_id, "kind": ref.kind, "item_id": ref.id}
        existing = await self._repository.get(**key)
        if existing is not None:
            return _favorite(existing)
        if await self._repository.count(user_id=user_id) >= MAX_FAVORITES:
            raise ConflictError(
                f"A member keeps at most {MAX_FAVORITES} favorites. Remove one first."
            )
        try:
            await self._repository.add(**key)
            await self._session.commit()
        except Exception as exc:
            await self._session.rollback()
            raise InfrastructureError(f"Failed to add favorite: {exc}") from exc
        logger.info("event=tactic.favorite_added user_id=%s kind=%s", user_id, ref.kind)
        return _favorite(await self._repository.get(**key))

    async def remove_favorite(self, *, user_id: int, ref: FavoriteRef) -> None:
        try:
            await self._repository.remove(
                user_id=user_id, kind=ref.kind, item_id=ref.id
            )
            await self._session.commit()
        except Exception as exc:
            await self._session.rollback()
            raise InfrastructureError(f"Failed to remove favorite: {exc}") from exc
        logger.info(
            "event=tactic.favorite_removed user_id=%s kind=%s", user_id, ref.kind
        )
