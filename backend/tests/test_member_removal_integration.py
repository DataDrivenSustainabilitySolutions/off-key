"""Permanent account removal against real PostgreSQL and authenticated HTTP routes."""

import asyncio
import hashlib

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from httpx import ASGITransport, AsyncClient
from off_key_api_gateway.services.auth import create_jwt
from off_key_core.db.base import get_db_async
from off_key_core.db.models import Charger, Favorite, RememberedSession, User
from off_key_core.schemas.members import MemberInvitation, MemberUpdate
from off_key_tactic_middleware.api.collection_auth import current_member
from off_key_tactic_middleware.api.v1.members import router
from off_key_tactic_middleware.domain import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from off_key_tactic_middleware.services.members import MemberService
from off_key_tactic_middleware.services.remembered_sessions import (
    RememberedSessionService,
)
from sqlalchemy import select

from .test_gateway_auth_token_types import _set_auth_env
from .test_membership_integration import PASSWORD, bootstrap


@pytest_asyncio.fixture
async def removal_database(member_database, monkeypatch):
    _set_auth_env(monkeypatch)
    engine, sessions = member_database
    async with engine.begin() as connection:
        await connection.run_sync(Charger.__table__.create)
        await connection.run_sync(Favorite.__table__.create)
    return sessions


def access_token(user):
    return create_jwt(
        {
            "sub": user.email,
            "user_id": user.id,
            "session_version": user.session_version,
        }
    )


def member_app(sessions):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def database():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db_async] = database
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "verified"), [("user", True), ("admin", True), ("user", False)]
)
async def test_disabled_member_removal_cleans_personal_data_and_allows_fresh_invitation(
    removal_database, role, verified
):
    sessions = removal_database
    admin_id = await bootstrap(sessions)
    async with sessions() as session:
        service = MemberService(session)
        actor = await session.get(User, admin_id)
        admin_headers = {"Authorization": f"Bearer {access_token(actor)}"}
        invitation = await service.invite(
            MemberInvitation(email="remove@example.com", role=role), actor
        )
        if verified:
            await service.accept_invitation(invitation["token"], PASSWORD)
        target = await session.scalar(
            select(User).where(User.email == invitation["email"])
        )
        user_id = target.id
        old_token = access_token(target)
        remembered = await RememberedSessionService(session).create(target)
        reset = await service.request_password_reset(target.email) if verified else None
        session.add(Charger(charger_id="shared-reading"))
        await session.flush()
        session.add_all(
            Favorite(user_id=owner, charger_id="shared-reading")
            for owner in (admin_id, user_id)
        )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=member_app(sessions)), base_url="http://test"
    ) as client:
        path = f"/api/v1/members/{user_id}"
        active = await client.delete(path, headers=admin_headers)
        assert active.status_code == 409
        assert "Disable this member" in active.json()["detail"]
        disabled = await client.put(
            path, headers=admin_headers, json={"role": role, "is_active": False}
        )
        assert disabled.status_code == 200
        removed = await client.delete(path, headers=admin_headers)
        assert removed.status_code == 204 and removed.content == b""
        assert (await client.delete(path, headers=admin_headers)).status_code == 404
        listed = await client.get("/api/v1/members", headers=admin_headers)
        assert [member["id"] for member in listed.json()] == [admin_id]

    async with sessions() as session:
        assert await session.get(User, user_id) is None
        assert list(await session.scalars(select(Favorite.user_id))) == [admin_id]
        assert await session.get(Charger, "shared-reading") is not None
        assert (
            await session.get(
                RememberedSession,
                hashlib.sha256(remembered["token"].encode()).hexdigest(),
            )
            is None
        )
        with pytest.raises(AuthenticationError):
            await RememberedSessionService(session).refresh(remembered["token"])
        service = MemberService(session)
        with pytest.raises(ValidationError):
            await service.accept_invitation(invitation["token"], PASSWORD)
        await session.rollback()
        if reset:
            with pytest.raises(ValidationError):
                await service.reset_password(reset["token"], PASSWORD)
            await session.rollback()
        actor = await session.get(User, admin_id)
        fresh = await service.invite(MemberInvitation(email=invitation["email"]), actor)
        await service.accept_invitation(fresh["token"], PASSWORD)
        replacement = await session.scalar(
            select(User).where(User.email == invitation["email"])
        )
        assert replacement.id != user_id and replacement.is_active
        assert list(await session.scalars(select(Favorite.user_id))) == [admin_id]

    async with sessions() as session:
        credential = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=old_token
        )
        with pytest.raises(HTTPException) as denied:
            await current_member(credential, session)
        assert denied.value.status_code == 401


@pytest.mark.asyncio
async def test_removal_requires_current_administrator_and_protects_active_accounts(
    removal_database,
):
    sessions = removal_database
    admin_id = await bootstrap(sessions)
    async with sessions() as session:
        service = MemberService(session)
        actor = await session.get(User, admin_id)
        invitation = await service.invite(
            MemberInvitation(email="user@example.com"), actor
        )
        await service.accept_invitation(invitation["token"], PASSWORD)
        user = await session.scalar(
            select(User).where(User.email == invitation["email"])
        )
        user_headers = {"Authorization": f"Bearer {access_token(user)}"}
        admin_headers = {"Authorization": f"Bearer {access_token(actor)}"}

    async with AsyncClient(
        transport=ASGITransport(app=member_app(sessions)), base_url="http://test"
    ) as client:
        path = f"/api/v1/members/{admin_id}"
        assert (await client.delete(path)).status_code == 401
        assert (await client.delete(path, headers=user_headers)).status_code == 403
        assert (await client.delete(path, headers=admin_headers)).status_code == 409
        assert (
            await client.put(
                path, headers=admin_headers, json={"role": "admin", "is_active": False}
            )
        ).status_code == 409
        assert (
            await client.delete("/api/v1/members/999999", headers=admin_headers)
        ).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("removal_first", [False, True])
async def test_enabling_and_removal_are_serialized(removal_database, removal_first):
    sessions = removal_database
    admin_id = await bootstrap(sessions)
    async with sessions() as session:
        service = MemberService(session)
        actor = await session.get(User, admin_id)
        invitation = await service.invite(
            MemberInvitation(email="race@example.com"), actor
        )
        target = await session.scalar(
            select(User).where(User.email == invitation["email"])
        )
        user_id = target.id
        await service.update(user_id, MemberUpdate(role="user", is_active=False), actor)

    async def mutate(remove):
        async with sessions() as session:
            actor = await session.get(User, admin_id)
            service = MemberService(session)
            try:
                if remove:
                    await service.remove(user_id, actor)
                    return "removed"
                await service.update(
                    user_id, MemberUpdate(role="user", is_active=True), actor
                )
                return "enabled"
            except ConflictError:
                await session.rollback()
                return "active"
            except NotFoundError:
                await session.rollback()
                return "missing"

    outcomes = set(
        await asyncio.gather(mutate(removal_first), mutate(not removal_first))
    )
    assert outcomes in ({"removed", "missing"}, {"enabled", "active"})
    async with sessions() as session:
        target = await session.get(User, user_id)
        if "removed" in outcomes:
            assert target is None
        else:
            assert target.is_active
        assert (await session.get(User, admin_id)).is_active
