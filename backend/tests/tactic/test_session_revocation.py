"""Revocation fences concurrent rotation and already-issued access tokens."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from jose import jwt
from off_key_api_gateway.api.access import signed_in_member
from off_key_core.auth.tokens import (
    AccessClaims,
    access_token_digest,
    decode_access_token,
    issue_access_token,
)
from off_key_core.config.auth import get_auth_settings
from off_key_core.db.models import RememberedSession, RevokedAccessToken, User
from off_key_tactic_middleware.domain import AuthenticationError
from off_key_tactic_middleware.services.accounts.remembered_sessions import (
    RememberedSessionService,
)
from off_key_tactic_middleware.services.accounts.tokens import digest_token

from tests.support.env import set_auth_env
from tests.support.membership import bootstrap


@pytest.mark.parametrize("revoke_previous_generation", [False, True])
async def test_logout_waits_for_rotation_and_removes_the_replacement(
    member_database, revoke_previous_generation
):
    _, sessions = member_database
    user_id = await bootstrap(sessions)
    async with sessions() as session:
        service = RememberedSessionService(session)
        user = await session.get(User, user_id)
        original = (
            await service.create(user_id=user.id, session_version=user.session_version)
        )["token"]
        other = (
            await service.create(user_id=user.id, session_version=user.session_version)
        )["token"]
        row = await session.get(RememberedSession, digest_token(original))
        row.issued_at = datetime.now(UTC) - timedelta(days=2)
        await session.commit()
        current = original
        if revoke_previous_generation:
            current = (await service.refresh(original))["token"]
            row = await session.get(RememberedSession, digest_token(current))
            row.issued_at = datetime.now(UTC) - timedelta(days=2)
            await session.commit()

    inserted, release, revoking = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async with sessions() as rotating, sessions() as ending:
        commit = rotating.commit

        async def paused_commit():
            await rotating.flush()
            inserted.set()
            await release.wait()
            await commit()

        rotating.commit = paused_commit
        rotation = asyncio.create_task(
            RememberedSessionService(rotating).refresh(current)
        )
        await asyncio.wait_for(inserted.wait(), 3)

        async def revoke():
            revoking.set()
            await RememberedSessionService(ending).revoke(original)

        logout = asyncio.create_task(revoke())
        await revoking.wait()
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(logout), 0.05)
        finally:
            release.set()
        replacement = (await asyncio.wait_for(rotation, 3))["token"]
        await asyncio.wait_for(logout, 3)

    for token in (original, current, replacement):
        async with sessions() as session:
            with pytest.raises(AuthenticationError):
                await RememberedSessionService(session).refresh(token)
    async with sessions() as session:
        assert (await RememberedSessionService(session).refresh(other))["id"] == user_id


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("revoke_variant", [False, True])
async def test_bearer_logout_is_persistent_and_preserves_other_sign_ins(
    member_database, monkeypatch, legacy, revoke_variant
):
    set_auth_env(monkeypatch)
    _, sessions = member_database
    user_id = await bootstrap(sessions)
    async with sessions() as session:
        user = await session.get(User, user_id)
        claims = AccessClaims(
            sub=user.email, user_id=user.id, session_version=user.session_version
        )
        token, other = issue_access_token(claims), issue_access_token(claims)
        if legacy:
            payload = jwt.get_unverified_claims(token)
            del payload["jti"]
            settings = get_auth_settings()
            token = jwt.encode(
                payload,
                settings.JWT_SECRET.get_secret_value(),
                algorithm=settings.ALGORITHM,
            )
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        changed_padding_bits = token[:-1] + alphabet[alphabet.index(token[-1]) | 1]
        variants = [token, token + "=", token + "==", changed_padding_bits]
        for variant in variants:
            assert (await signed_in_member(variant, session)).id == user_id
        await RememberedSessionService(session).revoke_access(
            variants[-1] if revoke_variant else token
        )
        await RememberedSessionService(session).revoke_access(token)
    async with sessions() as session:
        for variant in variants:
            with pytest.raises(HTTPException) as failure:
                await signed_in_member(variant, session)
            assert failure.value.status_code == 401
        assert (
            await signed_in_member(
                other,
                session,
            )
        ).id == user_id


async def test_refresh_response_arriving_after_logout_cannot_restore_access(
    member_database, monkeypatch
):
    set_auth_env(monkeypatch)
    _, sessions = member_database
    user_id = await bootstrap(sessions)
    async with sessions() as session:
        service = RememberedSessionService(session)
        user = await session.get(User, user_id)
        cookie = (
            await service.create(user_id=user.id, session_version=user.session_version)
        )["token"]
        identity = await service.refresh(cookie)
        await service.revoke(cookie)
        late_token = issue_access_token(
            AccessClaims(
                sub=identity["email"],
                user_id=identity["id"],
                session_version=identity["session_version"],
                session_family=identity["session_family"],
            )
        )
    async with sessions() as session:
        with pytest.raises(HTTPException) as failure:
            await signed_in_member(
                late_token,
                session,
            )
        assert failure.value.status_code == 401


@pytest.mark.parametrize("legacy", [False, True])
async def test_other_logout_cannot_remove_a_still_accepted_revocation(
    member_database, monkeypatch, legacy
):
    from off_key_tactic_middleware.services.accounts import remembered_sessions

    set_auth_env(monkeypatch)
    _, sessions = member_database
    user_id = await bootstrap(sessions)
    async with sessions() as session:
        user = await session.get(User, user_id)
        claims = AccessClaims(
            sub=user.email, user_id=user.id, session_version=user.session_version
        )
        token = issue_access_token(claims, timedelta(seconds=2))
        other = issue_access_token(claims, timedelta(minutes=5))
        settings = get_auth_settings()
        payload = jwt.get_unverified_claims(token)
        if legacy:
            del payload["jti"]
            token = jwt.encode(
                payload,
                settings.JWT_SECRET.get_secret_value(),
                algorithm=settings.ALGORITHM,
            )
        await RememberedSessionService(session).revoke_access(token)

    class Clock(datetime):
        instant = datetime.fromtimestamp(
            payload["exp"] + settings.JWT_CLOCK_SKEW_SECONDS + 0.5, UTC
        )

        @classmethod
        def now(cls, tz=None):
            return cls.instant

    monkeypatch.setattr(jwt, "datetime", Clock)
    monkeypatch.setattr(remembered_sessions, "datetime", Clock)
    assert decode_access_token(token) == claims  # Still accepted during this second.
    async with sessions() as session:
        await RememberedSessionService(session).revoke_access(other)
        assert await session.get(RevokedAccessToken, access_token_digest(token))
        with pytest.raises(HTTPException) as failure:
            await signed_in_member(
                token,
                session,
            )
        assert failure.value.status_code == 401
        Clock.instant += timedelta(seconds=1)
        await RememberedSessionService(session).revoke_access(other)
        assert await session.get(RevokedAccessToken, access_token_digest(token)) is None
