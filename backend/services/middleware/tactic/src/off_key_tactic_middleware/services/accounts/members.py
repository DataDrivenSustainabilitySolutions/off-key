"""Single-installation membership and single-use account links."""

import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from off_key_core.config.logs import log_security_event
from off_key_core.db.locks import MEMBERSHIP_LOCK
from off_key_core.db.models import Favorite, User
from off_key_core.schemas.members import MemberInvitation, MemberUpdate
from off_key_core.schemas.user import normalize_email
from off_key_core.utils.enum import RoleEnum
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain import AuthenticationError, ConflictError, NotFoundError, ValidationError
from .tokens import digest_token


class MemberService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _lock_membership(self, actor: User | None = None) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": MEMBERSHIP_LOCK}
        )
        if actor is not None:
            await self.session.refresh(actor)
            if (
                not actor.is_active
                or not actor.is_verified
                or actor.role != RoleEnum.admin
            ):
                raise AuthenticationError("Administrator access is no longer available")

    async def _admin_count(self) -> int:
        # COUNT never yields NULL; the fallback only satisfies the type.
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(User)
                .where(
                    User.role == RoleEnum.admin,
                    User.is_active.is_(True),
                    User.is_verified.is_(True),
                )
            )
            or 0
        )

    async def list_members(self) -> list[User]:
        return list(
            (await self.session.scalars(select(User).order_by(User.email))).all()
        )

    async def bootstrap_invitation(
        self, email: str, *, resend: bool = False
    ) -> dict[str, str]:
        """Initialize an empty installation without changing existing access."""
        email = normalize_email(email)
        await self._lock_membership()
        if await self._admin_count():
            return {"status": "configured"}
        users = list((await self.session.scalars(select(User))).all())
        if users:
            if (
                len(users) != 1
                or users[0].email != email
                or users[0].role != RoleEnum.admin
                or users[0].is_verified
                or not users[0].is_active
            ):
                raise ConflictError(
                    "Existing accounts require operator recovery; "
                    "automatic setup will not create or promote an administrator."
                )
            user = users[0]
            if (
                not resend
                and user.verification_token
                and user.invitation_expires_at
                and user.invitation_expires_at > datetime.now(UTC)
            ):
                return {"status": "pending", "email": email}
        invitation = await self.invite(
            MemberInvitation(email=email, role=RoleEnum.admin)
        )
        return {"status": "created", **invitation}

    async def ensure_demo_viewer(self, email: str, password: str) -> dict[str, str]:
        """Keep the public demo's ordinary viewer member able to sign in."""
        email = normalize_email(email)
        await self._lock_membership()
        # Created only after the administrator, so first setup stays unchanged.
        if not await self._admin_count():
            return {"status": "waiting"}
        user = await self.session.scalar(
            select(User).where(User.email == email).with_for_update()
        )
        if user is not None and user.role != RoleEnum.user:
            raise ConflictError("The demo viewer must be an ordinary member")
        if user is not None and not user.is_active:
            # An administrator closed the demo; a deployment does not reopen it.
            return {"status": "disabled"}
        if (
            user is not None
            and user.is_verified
            and bcrypt.checkpw(password.encode(), user.hashed_password.encode())
        ):
            return {"status": "configured"}
        if user is None:
            user = User(
                email=email,
                role=RoleEnum.user,
                is_active=True,
                session_version=0,
            )
            self.session.add(user)
            status = "created"
        else:
            user.session_version += 1
            status = "updated"
        user.hashed_password = bcrypt.hashpw(
            password.encode(), bcrypt.gensalt()
        ).decode()
        user.is_verified = True
        user.verification_token = None
        user.invitation_expires_at = None
        await self.session.commit()
        log_security_event("demo_viewer_" + status, "operator", {"member_id": user.id})
        return {"status": status}

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
        user.verification_token = digest_token(token)
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

    async def remove(self, user_id: int, actor: User) -> None:
        await self._lock_membership(actor)
        user = await self.session.get(
            User, user_id, with_for_update=True, populate_existing=True
        )
        if user is None:
            raise NotFoundError("Member not found")
        if user.is_active:
            raise ConflictError("Disable this member before removing them")
        await self.session.execute(delete(Favorite).where(Favorite.user_id == user_id))
        # Remembered sessions are removed by their cascading foreign key.
        await self.session.delete(user)
        await self.session.commit()
        log_security_event("member_removed", actor.email, {"member_id": user_id})

    async def accept_invitation(self, token: str, password: str) -> None:
        await self._lock_membership()
        user = await self.session.scalar(
            select(User)
            .where(User.verification_token == digest_token(token))
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

    async def issue_reset_token(self, email: str) -> dict[str, str] | None:
        """Issue a random account-recovery token, storing only its SHA-256 digest."""
        user = await self.session.scalar(
            select(User).where(User.email == normalize_email(email)).with_for_update()
        )
        if user is None or not user.is_active or not user.is_verified:
            return None
        token = secrets.token_urlsafe(32)
        user.reset_token_hash = digest_token(token)
        user.reset_token_expires_at = datetime.now(UTC) + timedelta(minutes=30)
        await self.session.commit()
        return {"email": user.email, "token": token}

    async def reset_password(self, token: str, password: str) -> None:
        user = await self.session.scalar(
            select(User)
            .where(User.reset_token_hash == digest_token(token))
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
