"""Single-installation membership and single-use account links."""

import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from off_key_core.config.logs import log_security_event
from off_key_core.db.models import User
from off_key_core.schemas.members import MemberInvitation, MemberUpdate
from off_key_core.utils.enum import RoleEnum
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import AuthenticationError, ConflictError, NotFoundError, ValidationError


class MemberService:
    _TOKEN_HASH_KEY = os.getenv("MEMBER_TOKEN_HASH_KEY", "member-token-hash-key").encode()

    def __init__(self, session: AsyncSession):
        self.session = session

    @classmethod
    def _hash_token(cls, token: str) -> str:
        return hmac.new(cls._TOKEN_HASH_KEY, token.encode(), hashlib.sha256).hexdigest()

    async def _lock_membership(self, actor: User | None = None) -> None:
        await self.session.execute(text("SELECT pg_advisory_xact_lock(73128004)"))
        if actor is not None:
            await self.session.refresh(actor)
            if (
                not actor.is_active
                or not actor.is_verified
                or actor.role != RoleEnum.admin
            ):
                raise AuthenticationError("Administrator access is no longer available")

    async def _admin_count(self) -> int:
        return await self.session.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.role == RoleEnum.admin,
                User.is_active.is_(True),
                User.is_verified.is_(True),
            )
        )

    async def list_members(self) -> list[User]:
        return list(
            (await self.session.scalars(select(User).order_by(User.email))).all()
        )

    async def invite(
        self, invitation: MemberInvitation, actor: User | None = None
    ) -> dict[str, str]:
        await self._lock_membership(actor)
        if actor is None and await self._admin_count():
            raise ConflictError(
                "An administrator already exists; use member management"
            )
        user = await self.session.scalar(
            select(User).where(User.email == str(invitation.email)).with_for_update()
        )
        if user is not None and (user.is_verified or not user.is_active):
            raise ConflictError(
                "This account already exists; manage its access instead"
            )
        if user is None:
            user = User(
                email=str(invitation.email),
                hashed_password="!",
                is_verified=False,
                is_active=True,
                session_version=0,
            )
            self.session.add(user)
        token = secrets.token_urlsafe(32)
        user.role = invitation.role
        user.verification_token = self._hash_token(token)
        user.invitation_expires_at = datetime.now(UTC) + timedelta(hours=48)
        await self.session.commit()
        log_security_event(
            "member_invited",
            actor.email if actor else "operator",
            {"member_id": user.id, "role": user.role.value},
        )
        return {"email": user.email, "token": token}

    async def update(self, user_id: int, change: MemberUpdate, actor: User) -> User:
        await self._lock_membership(actor)
        user = await self.session.get(
            User, user_id, with_for_update=True, populate_existing=True
        )
        if user is None:
            raise NotFoundError("Member not found")
        loses_admin = change.role != RoleEnum.admin or not change.is_active
        if (
            user.role == RoleEnum.admin
            and user.is_active
            and user.is_verified
            and loses_admin
            and await self._admin_count() <= 1
        ):
            raise ConflictError("Keep at least one active administrator")
        if user.role != change.role or user.is_active != change.is_active:
            user.session_version += 1
            user.reset_token_hash = None
            user.reset_token_expires_at = None
        user.role = change.role
        user.is_active = change.is_active
        if not user.is_active:
            user.verification_token = None
            user.invitation_expires_at = None
        await self.session.commit()
        log_security_event(
            "member_access_changed",
            actor.email,
            {"member_id": user.id, "role": user.role.value, "active": user.is_active},
        )
        return user

    async def accept_invitation(self, token: str, password: str) -> None:
        await self._lock_membership()
        user = await self.session.scalar(
            select(User)
            .where(User.verification_token == self._hash_token(token))
            .with_for_update()
        )
        if (
            user is None
            or not user.is_active
            or user.is_verified
            or user.invitation_expires_at is None
            or user.invitation_expires_at <= datetime.now(UTC)
        ):
            raise ValidationError("Invalid or expired invitation")
        user.hashed_password = bcrypt.hashpw(
            password.encode(), bcrypt.gensalt()
        ).decode()
        user.is_verified = True
        user.verification_token = None
        user.invitation_expires_at = None
        user.session_version += 1
        await self.session.commit()
        log_security_event("invitation_accepted", user.email, {"member_id": user.id})

    async def request_password_reset(self, email: str) -> dict[str, str] | None:
        user = await self.session.scalar(
            select(User).where(User.email == email).with_for_update()
        )
        if user is None or not user.is_active or not user.is_verified:
            return None
        token = secrets.token_urlsafe(32)
        user.reset_token_hash = self._hash_token(token)
        user.reset_token_expires_at = datetime.now(UTC) + timedelta(minutes=30)
        await self.session.commit()
        return {"email": user.email, "token": token}

    async def reset_password(self, token: str, password: str) -> None:
        user = await self.session.scalar(
            select(User)
            .where(User.reset_token_hash == self._hash_token(token))
            .with_for_update()
        )
        if (
            user is None
            or not user.is_active
            or not user.is_verified
            or user.reset_token_expires_at is None
            or user.reset_token_expires_at <= datetime.now(UTC)
        ):
            raise ValidationError("Invalid or expired reset link")
        user.hashed_password = bcrypt.hashpw(
            password.encode(), bcrypt.gensalt()
        ).decode()
        user.reset_token_hash = None
        user.reset_token_expires_at = None
        user.session_version += 1
        await self.session.commit()
        log_security_event("password_reset_success", user.email, {"member_id": user.id})
