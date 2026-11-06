"""Favourites are per member, idempotent, bounded, and roll back failed writes."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from off_key_core.schemas.favorites import MAX_FAVORITES, FavoriteRef
from off_key_tactic_middleware.domain import ConflictError, InfrastructureError
from off_key_tactic_middleware.services.data.favorites import FavoriteService
from pydantic import ValidationError

READING = FavoriteRef(kind="reading", id="line/temperature")
MONITOR = FavoriteRef(kind="monitor", id="m1")


class Favorites:
    """An in-memory FavoriteRepository."""

    def __init__(self):
        self.rows = {}

    async def list(self, *, user_id, kind=None):
        return [
            row
            for key, row in self.rows.items()
            if key[0] == user_id and kind in (None, key[1])
        ]

    async def get(self, *, user_id, kind, item_id):
        return self.rows.get((user_id, kind, item_id))

    async def count(self, *, user_id):
        return sum(key[0] == user_id for key in self.rows)

    async def add(self, *, user_id, kind, item_id):
        self.rows.setdefault(
            (user_id, kind, item_id),
            SimpleNamespace(kind=kind, item_id=item_id, created_at=datetime.now(UTC)),
        )

    async def remove(self, *, user_id, kind, item_id):
        self.rows.pop((user_id, kind, item_id), None)


def pairs(favorites):
    return [(favorite.kind, favorite.id) for favorite in favorites]


@pytest.mark.asyncio
async def test_members_keep_their_own_favourites_of_every_kind():
    session = AsyncMock()
    service = FavoriteService(session, Favorites())

    added = await service.add_favorite(user_id=1, ref=READING)
    await service.add_favorite(user_id=1, ref=MONITOR)
    await service.add_favorite(user_id=2, ref=FavoriteRef(kind="device", id="c2"))

    assert (added.kind, added.id) == ("reading", "line/temperature")
    assert pairs(await service.list_favorites(user_id=1)) == [
        ("reading", "line/temperature"),
        ("monitor", "m1"),
    ]
    assert pairs(await service.list_favorites(user_id=1, kind="monitor")) == [
        ("monitor", "m1")
    ]
    await service.remove_favorite(user_id=1, ref=READING)
    assert pairs(await service.list_favorites(user_id=1)) == [("monitor", "m1")]
    assert pairs(await service.list_favorites(user_id=2)) == [("device", "c2")]


@pytest.mark.asyncio
async def test_adding_twice_and_removing_absent_favourites_change_nothing():
    session = AsyncMock()
    service = FavoriteService(session, Favorites())
    first = await service.add_favorite(user_id=1, ref=READING)

    assert await service.add_favorite(user_id=1, ref=READING) == first
    await service.remove_favorite(user_id=2, ref=READING)
    assert pairs(await service.list_favorites(user_id=1)) == [
        ("reading", "line/temperature")
    ]
    assert session.commit.await_count == 2


@pytest.mark.asyncio
async def test_a_member_keeps_at_most_the_maximum_number_of_favourites():
    session = AsyncMock()
    service = FavoriteService(session, Favorites())
    for index in range(MAX_FAVORITES):
        await service.add_favorite(
            user_id=1, ref=FavoriteRef(kind="device", id=f"c{index}")
        )

    with pytest.raises(ConflictError, match="at most 256"):
        await service.add_favorite(user_id=1, ref=READING)
    # One the member already has is still answered, and others are unaffected.
    assert (
        await service.add_favorite(user_id=1, ref=FavoriteRef(kind="device", id="c0"))
    ).id
    await service.add_favorite(user_id=2, ref=READING)


@pytest.mark.parametrize(
    "value",
    [
        {"kind": "service", "id": "m1"},
        {"kind": "reading", "id": ""},
        {"kind": "reading", "id": "x" * 281},
        {"kind": "reading", "id": "line\ntemperature"},
        {"kind": "reading", "id": "a", "label": "extra"},
    ],
)
def test_favourites_name_a_known_kind_and_a_printable_id(value):
    with pytest.raises(ValidationError):
        FavoriteRef.model_validate(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["add_favorite", "remove_favorite"])
async def test_failed_commits_roll_back_and_surface_as_infrastructure_errors(
    operation,
):
    session = AsyncMock()
    session.commit.side_effect = RuntimeError("database gone")
    service = FavoriteService(session, Favorites())

    with pytest.raises(InfrastructureError, match="database gone"):
        await getattr(service, operation)(user_id=1, ref=READING)
    session.rollback.assert_awaited_once()
