"""Membership invariants against an explicitly supplied disposable database."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from off_key_api_gateway.services.auth import create_jwt
from off_key_core.db.migrate import migration_files
from off_key_core.db.models import User
from off_key_core.schemas.members import MemberInvitation, MemberUpdate
from off_key_core.utils import mail
from off_key_core.utils.enum import RoleEnum
from off_key_tactic_middleware import bootstrap_admin
from off_key_tactic_middleware.api.collection_auth import current_member
from off_key_tactic_middleware.domain import (
    AuthenticationError,
    ConflictError,
    ValidationError,
)
from off_key_tactic_middleware.repositories import UserRepository
from off_key_tactic_middleware.services.data.users import UserService
from off_key_tactic_middleware.services.members import MemberService
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .test_gateway_auth_token_types import _set_auth_env

PASSWORD = "correct horse battery staple"


@pytest_asyncio.fixture
async def member_database():
    url = os.getenv("TEST_SCHEMA_DATABASE_URL")
    if not url:
        pytest.skip("TEST_SCHEMA_DATABASE_URL must point to a disposable database")
    schema = "members_" + uuid4().hex
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema}}
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(User.__table__.create)
        yield engine, async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin.dispose()


async def bootstrap(sessions):
    async with sessions() as session:
        service = MemberService(session)
        invitation = await service.invite(
            MemberInvitation(email="admin@example.com", role="admin")
        )
        await service.accept_invitation(invitation["token"], PASSWORD)
        return (
            await session.scalar(select(User).where(User.email == "admin@example.com"))
        ).id


@pytest.mark.asyncio
async def test_automatic_bootstrap_preserves_pending_and_completed_setup(
    member_database,
):
    _, sessions = member_database

    async def initialize():
        async with sessions() as session:
            return await MemberService(session).bootstrap_invitation(
                "admin@example.com"
            )

    results = await asyncio.gather(initialize(), initialize())
    assert sorted(result["status"] for result in results) == ["created", "pending"]
    invitation = next(result for result in results if result["status"] == "created")
    async with sessions() as session:
        service = MemberService(session)
        assert await service.bootstrap_invitation("admin@example.com") == {
            "status": "pending",
            "email": "admin@example.com",
        }
        await service.accept_invitation(invitation["token"], PASSWORD)
        assert await service.bootstrap_invitation("other@example.com", resend=True) == {
            "status": "configured"
        }
        users = list(await session.scalars(select(User)))
        assert len(users) == 1
        assert users[0].email == "admin@example.com"


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
async def test_bootstrap_replaces_expired_or_explicitly_resent_links(
    member_database, expired
):
    _, sessions = member_database
    async with sessions() as session:
        service = MemberService(session)
        original = await service.bootstrap_invitation("admin@example.com")
        if expired:
            user = await session.scalar(select(User))
            user.invitation_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        replacement = await service.bootstrap_invitation(
            "admin@example.com", resend=not expired
        )
        assert replacement["status"] == "created"
        with pytest.raises(ValidationError):
            await service.accept_invitation(original["token"], PASSWORD)
        await session.rollback()
        await service.accept_invitation(replacement["token"], PASSWORD)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"email": "someone-else@example.com"},
        {"role": RoleEnum.user},
        {"is_active": False},
    ],
)
async def test_bootstrap_refuses_to_change_existing_access(member_database, change):
    _, sessions = member_database
    async with sessions() as session:
        service = MemberService(session)
        await service.bootstrap_invitation("admin@example.com")
        user = await session.scalar(select(User))
        for key, value in change.items():
            setattr(user, key, value)
        await session.commit()
        with pytest.raises(ConflictError, match="operator recovery"):
            await service.bootstrap_invitation("admin@example.com", resend=True)


@pytest.mark.asyncio
async def test_bootstrap_cli_email_delivery_and_recovery(
    member_database, monkeypatch, capsys
):
    engine, sessions = member_database
    monkeypatch.setattr(bootstrap_admin, "load_env", lambda: None)
    monkeypatch.setattr(bootstrap_admin, "get_async_session_local", lambda: sessions)
    monkeypatch.setattr(bootstrap_admin, "get_async_engine", lambda: engine)
    monkeypatch.setattr(
        bootstrap_admin,
        "get_auth_settings",
        lambda: SimpleNamespace(SUPERUSER_MAIL="admin@example.com"),
    )
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://dashboard.example.com")
    monkeypatch.setattr(mail, "get_mail_config", lambda: None)
    send = AsyncMock(side_effect=RuntimeError("sensitive transport details"))
    monkeypatch.setattr(mail, "send_invitation_email", send)

    with pytest.raises(RuntimeError, match="--send-email --resend") as error:
        await bootstrap_admin.main(send_email=True)
    assert "sensitive transport details" not in str(error.value)
    assert capsys.readouterr().out == ""
    failed_token = send.call_args.args[1]

    send.reset_mock(side_effect=True)
    await bootstrap_admin.main(send_email=True)
    assert '"status": "pending"' in capsys.readouterr().out
    send.assert_not_awaited()

    await bootstrap_admin.main(send_email=True, resend=True)
    sent_email, token = send.call_args.args
    assert sent_email == "admin@example.com"
    output = capsys.readouterr().out
    assert '"status": "sent"' in output
    assert token not in output
    assert "token" not in output
    async with sessions() as session:
        service = MemberService(session)
        with pytest.raises(ValidationError):
            await service.accept_invitation(failed_token, PASSWORD)
        await session.rollback()
        await service.accept_invitation(token, PASSWORD)
    send.reset_mock()
    await bootstrap_admin.main(send_email=True, resend=True)
    assert '"status": "configured"' in capsys.readouterr().out
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_invitation_reset_and_immediate_session_revocation(
    member_database, monkeypatch
):
    _set_auth_env(monkeypatch)
    _, sessions = member_database
    admin_id = await bootstrap(sessions)
    async with sessions() as session:
        service = MemberService(session)
        actor = await session.get(User, admin_id)
        with pytest.raises(ConflictError, match="already exists"):
            await service.invite(
                MemberInvitation(email="another-admin@example.com", role="admin")
            )
        await session.rollback()
        invitation = await service.invite(
            MemberInvitation(email="member@example.com"), actor
        )
        pending = await session.scalar(
            select(User).where(User.email == invitation["email"])
        )
        assert pending.verification_token == service._hash_token(invitation["token"])
        replacement = await service.invite(
            MemberInvitation(email="member@example.com"), actor
        )
        with pytest.raises(ValidationError):
            await service.accept_invitation(invitation["token"], PASSWORD)
        await session.rollback()
        await service.accept_invitation(replacement["token"], PASSWORD)
        with pytest.raises(ValidationError):
            await service.accept_invitation(replacement["token"], PASSWORD)
        await session.rollback()

    async def login():
        async with sessions() as session:
            return await UserService(session, UserRepository(session)).authenticate(
                email="member@example.com", password=PASSWORD
            )

    claims = await login()
    credential = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=create_jwt(
            {
                "sub": claims["email"],
                "user_id": claims["id"],
                "session_version": claims["session_version"],
            }
        ),
    )
    async with sessions() as session:
        assert (await current_member(credential, session)).id == claims["id"]
        reset = await MemberService(session).request_password_reset(
            "member@example.com"
        )
        await MemberService(session).reset_password(reset["token"], PASSWORD)
        with pytest.raises(ValidationError):
            await MemberService(session).reset_password(reset["token"], PASSWORD)
        await session.rollback()
    async with sessions() as session:
        with pytest.raises(HTTPException) as denied:
            await current_member(credential, session)
        assert denied.value.status_code == 401

    claims = await login()
    credential = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=create_jwt(
            {
                "sub": claims["email"],
                "user_id": claims["id"],
                "session_version": claims["session_version"],
            }
        ),
    )
    async with sessions() as session:
        actor = await session.get(User, admin_id)
        await MemberService(session).update(
            claims["id"], MemberUpdate(role="user", is_active=False), actor
        )
    async with sessions() as session:
        with pytest.raises(HTTPException) as denied:
            await current_member(credential, session)
        assert denied.value.status_code == 401
        assert (
            await MemberService(session).request_password_reset("member@example.com")
            is None
        )
    with pytest.raises(AuthenticationError):
        await login()
    async with sessions() as session:
        actor = await session.get(User, admin_id)
        await MemberService(session).update(
            claims["id"], MemberUpdate(role="user", is_active=True), actor
        )
    async with sessions() as session:
        with pytest.raises(HTTPException):
            await current_member(credential, session)
    assert (await login())["id"] == claims["id"]


@pytest.mark.asyncio
async def test_expired_links_and_last_administrator_race(member_database):
    _, sessions = member_database
    admin_id = await bootstrap(sessions)
    async with sessions() as session:
        service = MemberService(session)
        actor = await session.get(User, admin_id)
        invitation = await service.invite(
            MemberInvitation(email="other@example.com", role="admin"), actor
        )
        pending = await session.scalar(
            select(User).where(User.email == invitation["email"])
        )
        pending.invitation_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
        with pytest.raises(ValidationError):
            await service.accept_invitation(invitation["token"], PASSWORD)
        await session.rollback()
        invitation = await service.invite(
            MemberInvitation(email="other@example.com", role="admin"), actor
        )
        await service.accept_invitation(invitation["token"], PASSWORD)
        other_id = (
            await session.scalar(select(User).where(User.email == invitation["email"]))
        ).id
        reset = await service.request_password_reset("other@example.com")
        pending = await session.get(User, other_id)
        pending.reset_token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
        with pytest.raises(ValidationError):
            await service.reset_password(reset["token"], PASSWORD)
        await session.rollback()

    async def demote(user_id):
        async with sessions() as session:
            actor = await session.get(User, user_id)
            try:
                await MemberService(session).update(
                    user_id, MemberUpdate(role="user", is_active=True), actor
                )
                return "updated"
            except ConflictError:
                await session.rollback()
                return "last-admin"

    assert sorted(await asyncio.gather(demote(admin_id), demote(other_id))) == [
        "last-admin",
        "updated",
    ]
    async with sessions() as session:
        remaining = list(
            await session.scalars(select(User).where(User.role == RoleEnum.admin))
        )
        assert len(remaining) == 1
        with pytest.raises(ConflictError):
            await MemberService(session).update(
                remaining[0].id,
                MemberUpdate(role="admin", is_active=False),
                remaining[0],
            )


@pytest.mark.asyncio
async def test_membership_migration_preserves_existing_accounts(member_database):
    engine, sessions = member_database
    admin_id = await bootstrap(sessions)
    async with engine.begin() as connection:
        for column in (
            "is_active",
            "session_version",
            "invitation_expires_at",
            "reset_token_hash",
            "reset_token_expires_at",
        ):
            await connection.execute(text(f"ALTER TABLE users DROP COLUMN {column}"))
        await connection.execute(
            text("UPDATE users SET verification_token = 'legacy-link'")
        )
    migration = migration_files()["001_membership.sql"]
    async with engine.begin() as connection:
        raw = await connection.get_raw_connection()
        await raw.driver_connection.execute(migration)
        await raw.driver_connection.execute(migration)
    async with sessions() as session:
        user = await session.get(User, admin_id)
        assert user.email == "admin@example.com"
        assert user.is_verified and user.is_active and user.role == RoleEnum.admin
        assert user.session_version == 0
        assert user.verification_token is None
        assert user.hashed_password.startswith("$2")


@pytest.mark.asyncio
async def test_reset_between_actor_read_and_self_update_revokes_new_session(
    member_database, monkeypatch
):
    _set_auth_env(monkeypatch)
    _, sessions = member_database
    admin_id = await bootstrap(sessions)
    async with sessions() as session:
        service = MemberService(session)
        actor = await session.get(User, admin_id)
        invite = await service.invite(
            MemberInvitation(email="second@example.com", role="admin"), actor
        )
        await service.accept_invitation(invite["token"], PASSWORD)

    async with sessions() as session:
        service = MemberService(session)
        actor = await session.get(User, admin_id)
        original_lock = service._lock_membership
        reset_version = None

        async def reset_after_actor_read(actor):
            nonlocal reset_version
            await original_lock(actor)
            async with sessions() as reset_session:
                reset_service = MemberService(reset_session)
                link = await reset_service.request_password_reset("admin@example.com")
                await reset_service.reset_password(link["token"], PASSWORD)
                reset_version = (
                    await reset_session.get(User, admin_id)
                ).session_version

        monkeypatch.setattr(service, "_lock_membership", reset_after_actor_read)
        changed = await service.update(
            admin_id, MemberUpdate(role="user", is_active=True), actor
        )
        assert changed.session_version == reset_version + 1
    credential = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=create_jwt(
            {
                "sub": "admin@example.com",
                "user_id": admin_id,
                "session_version": reset_version,
            }
        ),
    )
    async with sessions() as session:
        with pytest.raises(HTTPException) as denied:
            await current_member(credential, session)
        assert denied.value.status_code == 401
