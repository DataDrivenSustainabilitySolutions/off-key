"""Favourites are per member, unique, and roll back when a write fails."""

from unittest.mock import AsyncMock

import pytest
from off_key_tactic_middleware.domain import (
    ConflictError,
    InfrastructureError,
    NotFoundError,
)
from off_key_tactic_middleware.services.data.favorites import FavoriteService


class Favorites:
    """An in-memory FavoriteRepository."""

    def __init__(self, *rows):
        self.rows = list(rows)

    async def list_by_user_id(self, *, user_id):
        return [row for row in self.rows if row.user_id == user_id]

    async def get(self, *, user_id, charger_id):
        return next(
            (
                row
                for row in self.rows
                if (row.user_id, row.charger_id) == (user_id, charger_id)
            ),
            None,
        )

    async def add(self, favorite):
        self.rows.append(favorite)

    async def delete(self, favorite):
        self.rows.remove(favorite)


@pytest.mark.asyncio
async def test_members_add_list_and_remove_only_their_own_favourites():
    session = AsyncMock()
    service = FavoriteService(session, Favorites())

    await service.add_favorite(user_id=1, charger_id="c1")
    await service.add_favorite(user_id=2, charger_id="c2")
    assert await service.list_user_favorites(user_id=1) == ["c1"]

    assert await service.remove_favorite(user_id=1, charger_id="c1") == {
        "message": "Favorite removed"
    }
    assert await service.list_user_favorites(user_id=1) == []
    assert await service.list_user_favorites(user_id=2) == ["c2"]
    assert session.commit.await_count == 3


@pytest.mark.asyncio
async def test_duplicate_and_missing_favourites_are_rejected_without_writing():
    session = AsyncMock()
    service = FavoriteService(session, Favorites())
    await service.add_favorite(user_id=1, charger_id="c1")

    with pytest.raises(ConflictError, match="already favorited"):
        await service.add_favorite(user_id=1, charger_id="c1")
    with pytest.raises(NotFoundError, match="Favorite not found"):
        await service.remove_favorite(user_id=2, charger_id="c1")
    assert session.commit.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["add_favorite", "remove_favorite"])
async def test_failed_commits_roll_back_and_surface_as_infrastructure_errors(
    operation,
):
    session = AsyncMock()
    repository = Favorites()
    service = FavoriteService(session, repository)
    if operation == "remove_favorite":
        await service.add_favorite(user_id=1, charger_id="c1")
    session.commit.side_effect = RuntimeError("database gone")

    with pytest.raises(InfrastructureError, match="database gone"):
        await getattr(service, operation)(user_id=1, charger_id="c1")
    session.rollback.assert_awaited_once()
