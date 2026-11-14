"""Member favorites through the API's routes against real PostgreSQL."""

import asyncio

import pytest
import pytest_asyncio
from off_key_core.db.models import MemberFavorite, User
from sqlalchemy import delete, select

from tests.support.env import set_auth_env
from tests.support.gateway import gateway_app
from tests.support.http import asgi_client
from tests.support.tokens import access_token

PATH = "/v1/favorites"
MEMBERS = {}


@pytest_asyncio.fixture
async def favorites_app(member_database, monkeypatch):
    set_auth_env(monkeypatch)
    engine, sessions = member_database
    async with engine.begin() as connection:
        await connection.run_sync(MemberFavorite.__table__.create)
    members = [
        User(
            id=index,
            email=f"m{index}@example.test",
            hashed_password="h",
            role="user",
            is_active=True,
            is_verified=True,
            session_version=0,
        )
        for index in (1, 2)
    ]
    async with sessions() as session:
        session.add_all(members)
        await session.commit()
    for user in members:
        MEMBERS[user.id] = {"Authorization": f"Bearer {access_token(user)}"}
    return gateway_app(sessions=sessions), sessions


def by(member: int) -> dict:
    """Sign a request in as one of the two members."""
    return {"headers": MEMBERS[member]}


def pairs(response):
    return [(item["kind"], item["id"]) for item in response.json()]


@pytest.mark.asyncio
async def test_favorites_are_idempotent_ordered_and_scoped_to_their_member(
    favorites_app,
):
    app, sessions = favorites_app
    reading = {"kind": "reading", "id": "line/temperature"}
    async with asgi_client(app) as client:
        first = await client.post(PATH, **by(1), json=reading)
        again = await client.post(PATH, **by(1), json=reading)
        await client.post(PATH, **by(1), json={"kind": "monitor", "id": "m1"})
        await client.post(PATH, **by(2), json={"kind": "device", "id": "c1"})

        assert first.status_code == again.status_code == 200
        assert again.json() == first.json()
        assert pairs(await client.get(PATH, **by(1))) == [
            ("reading", "line/temperature"),
            ("monitor", "m1"),
        ]
        only = await client.get(PATH, **by(1), params={"kind": "monitor"})
        assert pairs(only) == [("monitor", "m1")]

        for _ in range(2):
            removed = await client.delete(PATH, **by(1), params=reading)
            assert removed.status_code == 204
        assert pairs(await client.get(PATH, **by(1))) == [("monitor", "m1")]
        assert pairs(await client.get(PATH, **by(2))) == [("device", "c1")]

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
            MemberFavorite(user_id=1, kind="device", item_id=f"c{index}")
            for index in range(256)
        )
        await session.commit()
    async with asgi_client(app) as client:
        full = await client.post(PATH, **by(1), json={"kind": "monitor", "id": "m1"})
        kept = await client.post(PATH, **by(1), json={"kind": "device", "id": "c0"})

    assert full.status_code == 409
    assert "Remove one first" in full.json()["detail"]
    assert kept.status_code == 200


@pytest.mark.asyncio
async def test_concurrent_additions_share_the_members_last_slot(favorites_app):
    app, sessions = favorites_app
    async with sessions() as session:
        session.add_all(
            MemberFavorite(user_id=1, kind="device", item_id=f"c{i}")
            for i in range(255)
        )
        await session.commit()
    async with asgi_client(app) as client:
        replies = await asyncio.gather(
            *(
                client.post(PATH, **by(1), json={"kind": "monitor", "id": f"m{i}"})
                for i in range(8)
            )
        )
        assert sorted(reply.status_code for reply in replies) == [200, *([409] * 7)]
        assert len((await client.get(PATH, **by(1))).json()) == 256
