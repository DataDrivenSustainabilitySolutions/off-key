"""Issue access credentials from remembered sessions after checking membership."""

import secrets
from datetime import UTC, datetime, timedelta

from off_key_core.auth.tokens import (
    InvalidAccessToken,
    access_token_digest,
    decode_access_token_with_expiry,
)
from off_key_core.config.logs import log_security_event
from off_key_core.db.models import RememberedSession, RevokedAccessToken, User
from off_key_core.schemas.sessions import REMEMBERED_SESSION_SECONDS
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain import AuthenticationError
from .tokens import digest_token

# Tabs that refresh together with the same cookie must not sign each other out.
ROTATION_GRACE = timedelta(seconds=30)
# A secret is replaced on the first refresh after this age, so a copied cookie
# stays usable for at most about a day before its reuse is detected. Rotating
# less often than every refresh keeps restored browser profiles working.
ROTATION_INTERVAL = timedelta(days=1)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class RememberedSessionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _issue(
        self,
        user: User,
        *,
        family_id: str | None,
        expires_at: datetime,
        issued_at: datetime,
    ) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = digest_token(token)
        self.session.add(
            RememberedSession(
                token_hash=token_hash,
                family_id=family_id or token_hash,
                user_id=user.id,
                session_version=user.session_version,
                expires_at=expires_at,
                issued_at=issued_at,
            )
        )
        return token

    async def create(self, user: User) -> dict:
        now = datetime.now(UTC)
        await self.session.execute(
            delete(RememberedSession).where(RememberedSession.expires_at <= now)
        )
        token = self._issue(
            user,
            family_id=None,
            expires_at=now + timedelta(seconds=REMEMBERED_SESSION_SECONDS),
            issued_at=now,
        )
        await self.session.commit()
        return {
            "token": token,
            "expires_in": REMEMBERED_SESSION_SECONDS,
            "session_family": digest_token(token),
        }

    async def _lock_family(self, token: str) -> str | None:
        family = await self.session.scalar(
            select(RememberedSession.family_id).where(
                RememberedSession.token_hash == digest_token(token)
            )
        )
        if family is not None:
            await self.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:family, 0))"),
                {"family": "off-key-session:" + family},
            )
        return family

    async def refresh(self, token: str) -> dict:
        """Exchange a day-old remembered secret for a new one in the same lifetime.

        Presenting a secret that was replaced outside the grace window means it
        was copied, so the whole sign-in is revoked.
        """
        await self._lock_family(token)
        # The read after the family lock gets a new READ COMMITTED snapshot.
        now = datetime.now(UTC)
        result = (
            await self.session.execute(
                select(RememberedSession, User)
                .join(User, User.id == RememberedSession.user_id)
                .where(
                    RememberedSession.token_hash == digest_token(token),
                    RememberedSession.expires_at > now,
                )
                .with_for_update(of=RememberedSession)
            )
        ).first()
        if result is None:
            raise AuthenticationError("This remembered session is no longer valid")
        remembered, user = result
        if (
            not user.is_active
            or not user.is_verified
            or user.session_version != remembered.session_version
        ):
            raise AuthenticationError("This remembered session is no longer valid")
        identity = {
            "id": user.id,
            "email": user.email,
            "session_version": user.session_version,
            "session_family": remembered.family_id,
        }
        if remembered.replaced_at is not None:
            if now - _utc(remembered.replaced_at) <= ROTATION_GRACE:
                # A concurrent refresh already set the replacement cookie.
                await self.session.commit()
                return identity
            await self.session.execute(
                delete(RememberedSession).where(
                    RememberedSession.family_id == remembered.family_id
                )
            )
            await self.session.commit()
            log_security_event(
                "remembered_session_reuse", user.email, {"member_id": user.id}
            )
            raise AuthenticationError("This remembered session is no longer valid")
        if now - _utc(remembered.issued_at) < ROTATION_INTERVAL:
            await self.session.commit()
            return identity
        remembered.replaced_at = now
        replacement = self._issue(
            user,
            family_id=remembered.family_id,
            expires_at=remembered.expires_at,
            issued_at=now,
        )
        await self.session.commit()
        expires_at = _utc(remembered.expires_at)
        return {
            **identity,
            "token": replacement,
            "expires_in": max(1, int((expires_at - now).total_seconds())),
        }

    async def revoke(self, token: str) -> None:
        family = await self._lock_family(token)
        if family is None:
            return
        await self.session.execute(
            delete(RememberedSession).where(RememberedSession.family_id == family)
        )
        await self.session.commit()

    async def revoke_access(self, token: str) -> None:
        try:
            _, expires_at = decode_access_token_with_expiry(token)
        except InvalidAccessToken:
            return  # Expired/invalid tokens already cannot authorize requests.
        await self.session.execute(
            delete(RevokedAccessToken).where(
                RevokedAccessToken.expires_at <= datetime.now(UTC)
            )
        )
        await self.session.execute(
            insert(RevokedAccessToken)
            .values(token_hash=access_token_digest(token), expires_at=expires_at)
            .on_conflict_do_nothing()
        )
        await self.session.commit()
