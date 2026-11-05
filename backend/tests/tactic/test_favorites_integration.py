"""Member favorites through TACTIC's routes against real PostgreSQL."""

import pytest
import pytest_asyncio
from fastapi import FastAPI
from off_key_core.db.base import get_db_async
from off_key_core.db.models import MemberFavorite, User
from off_key_tactic_middleware.api.v1.data_services import router
from sqlalchemy import delete, select

from tests.support.http import asgi_client

PATH = "/api/v1/data/users/{}/favorites"


@pytest_asyncio.fixture
async def favorites_app(member_database):
    engine, sessions = member_database
    async with engine.begin() as connection:
        await connection.run_sync(MemberFavorite.__table__.create)
    async with sessions() as session:
        session.add_all(
            User(id=index, email=f"m{index}@example.test", hashed_password="h")
            for index in (1, 2)
        )
        await session.commit()

    async def database():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/data")
    app.dependency_overrides[get_db_async] = database
    return app, sessions


def pairs(response):
    return [(item["kind"], item["id"]) for item in response.json()]


@pytest.mark.asyncio
async def test_favorites_are_idempotent_ordered_and_scoped_to_their_member(
    favorites_app,
):
    app, sessions = favorites_app
    reading = {"kind": "reading", "id": "line/temperature"}
    async with asgi_client(app) as client:
        first = await client.post(PATH.format(1), json=reading)
        again = await client.post(PATH.format(1), json=reading)
        await client.post(PATH.format(1), json={"kind": "monitor", "id": "m1"})
        await client.post(PATH.format(2), json={"kind": "entity", "id": "c1"})

        assert first.status_code == again.status_code == 200
        assert again.json() == first.json()
        assert pairs(await client.get(PATH.format(1))) == [
            ("reading", "line/temperature"),
            ("monitor", "m1"),
        ]
        only = await client.get(PATH.format(1), params={"kind": "monitor"})
        assert pairs(only) == [("monitor", "m1")]

        for _ in range(2):
            removed = await client.delete(PATH.format(1), params=reading)
            assert removed.status_code == 204
        assert pairs(await client.get(PATH.format(1))) == [("monitor", "m1")]
        assert pairs(await client.get(PATH.format(2))) == [("entity", "c1")]

    # Removing a member removes their favorites with them.
    async with sessions() as session:
        await session.execute(delete(User).where(User.id == 2))
        await session.commit()
        assert list(await session.scalars(select(MemberFavorite.user_id))) == [1]


@pytest.mark.asyncio
async def test_a_member_at_the_limit_is_told_to_remove_one_first(favorites_app):
    app, sessions = favorites_app
    async with sessions() as session:
        session.add_all(
            MemberFavorite(user_id=1, kind="entity", item_id=f"c{index}")
            for index in range(256)
        )
        await session.commit()
    async with asgi_client(app) as client:
        full = await client.post(PATH.format(1), json={"kind": "monitor", "id": "m1"})
        kept = await client.post(PATH.format(1), json={"kind": "entity", "id": "c0"})

    assert full.status_code == 409
    assert "Remove one first" in full.json()["detail"]
    assert kept.status_code == 200
