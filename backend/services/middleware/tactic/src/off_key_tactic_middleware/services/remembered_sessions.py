"""Issue access credentials from remembered sessions after checking membership."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from off_key_core.db.models import RememberedSession, User
from off_key_core.schemas.sessions import REMEMBERED_SESSION_SECONDS
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import AuthenticationError


class RememberedSessionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user: User) -> dict:
        now = datetime.now(UTC)
        await self.session.execute(
            delete(RememberedSession).where(RememberedSession.expires_at <= now)
        )
        token = secrets.token_urlsafe(32)
        self.session.add(
            RememberedSession(
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                user_id=user.id,
                session_version=user.session_version,
                expires_at=now + timedelta(seconds=REMEMBERED_SESSION_SECONDS),
            )
        )
        await self.session.commit()
        return {"token": token, "expires_in": REMEMBERED_SESSION_SECONDS}

    async def refresh(self, token: str) -> dict:
        result = (
            await self.session.execute(
                select(RememberedSession, User)
                .join(User, User.id == RememberedSession.user_id)
                .where(
                    RememberedSession.token_hash
                    == hashlib.sha256(token.encode()).hexdigest(),
                    RememberedSession.expires_at > datetime.now(UTC),
                )
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
        return {
            "id": user.id,
            "email": user.email,
            "session_version": user.session_version,
        }

    async def revoke(self, token: str) -> None:
        await self.session.execute(
            delete(RememberedSession).where(
                RememberedSession.token_hash
                == hashlib.sha256(token.encode()).hexdigest()
            )
        )
        await self.session.commit()
