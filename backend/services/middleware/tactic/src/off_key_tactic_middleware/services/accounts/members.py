"""Single-installation membership and single-use account links."""

import re
import secrets
import unicodedata
from datetime import UTC, datetime, timedelta

import bcrypt
from off_key_core.auth.permissions import (
    ADMIN_ROLE,
    BUILT_IN_ROLES,
    Permission,
    known_permissions,
    role_permissions,
)
from off_key_core.config.logs import log_security_event
from off_key_core.db.locks import MEMBERSHIP_LOCK
from off_key_core.db.models import MemberFavorite, MemberRole, User
from off_key_core.schemas.members import (
    MemberInvitation,
    MemberUpdate,
    RoleCreate,
    RoleProfile,
    RoleUpdate,
)
from off_key_core.schemas.user import normalize_email
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain import AuthenticationError, ConflictError, NotFoundError, ValidationError
from .tokens import digest_token


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _role_id(name: str) -> str:
    """A readable id for a new role: "Field engineers" becomes field-engineers."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:32].strip("-")
    if not slug or not slug[0].isalpha():
        slug = f"role-{slug}".rstrip("-")
    return slug if len(slug) > 1 else "role"


KEEP_A_MEMBER_MANAGER = "Keep at least one active member who can manage members"


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
                or not await self._manages_members(actor.role)
            ):
                raise AuthenticationError("Member management is no longer available")

    async def _manages_members(self, role_id: str) -> bool:
        role = await self.session.get(MemberRole, role_id, populate_existing=True)
        return role is not None and Permission.manage_members in role_permissions(
            role.id, role.permissions
        )

    async def _manager_count(self) -> int:
        """Active members who can manage members, so access can still change."""
        await self.session.flush()
        # COUNT never yields NULL; the fallback only satisfies the type.
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(User)
                .join(MemberRole, MemberRole.id == User.role)
                .where(
                    or_(
                        MemberRole.id == ADMIN_ROLE,
                        MemberRole.permissions.contains(
                            [Permission.manage_members.value]
                        ),
                    ),
                    User.is_active.is_(True),
                    User.is_verified.is_(True),
                )
            )
            or 0
        )

    async def _commit_keeping_a_manager(self) -> None:
        if not await self._manager_count():
            await self.session.rollback()
            raise ConflictError(KEEP_A_MEMBER_MANAGER)
        await self.session.commit()

    async def _role(self, role_id: str) -> MemberRole:
        role = await self.session.get(MemberRole, role_id, populate_existing=True)
        if role is None:
            raise ValidationError(f"There is no role {role_id!r}")
        return role

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
        if await self._manager_count():
            return {"status": "configured"}
        users = list((await self.session.scalars(select(User))).all())
        if users:
            if (
                len(users) != 1
                or users[0].email != email
                or users[0].role != ADMIN_ROLE
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
        invitation = await self.invite(MemberInvitation(email=email, role=ADMIN_ROLE))
        return {"status": "created", **invitation}

    async def invite(
        self, invitation: MemberInvitation, actor: User | None = None
    ) -> dict[str, str]:
        await self._lock_membership(actor)
        if actor is None and await self._manager_count():
            raise ConflictError(
                "An administrator already exists; use member management"
            )
        role = await self._role(invitation.role)
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
        user.member_role = role
        user.verification_token = digest_token(token)
        user.invitation_expires_at = datetime.now(UTC) + timedelta(hours=48)
        await self.session.commit()
        log_security_event(
            "member_invited",
            actor.email if actor else "operator",
            {"member_id": user.id, "role": role.id},
        )
        return {"email": user.email, "token": token}

    async def update(self, user_id: int, change: MemberUpdate, actor: User) -> User:
        await self._lock_membership(actor)
        user = await self.session.get(
            User, user_id, with_for_update=True, populate_existing=True
        )
        if user is None:
            raise NotFoundError("Member not found")
        role = await self._role(change.role)
        if user.role != change.role or user.is_active != change.is_active:
            user.session_version += 1
            user.reset_token_hash = None
            user.reset_token_expires_at = None
        user.member_role = role
        user.is_active = change.is_active
        if not user.is_active:
            user.verification_token = None
            user.invitation_expires_at = None
        await self._commit_keeping_a_manager()
        log_security_event(
            "member_access_changed",
            actor.email,
            {"member_id": user.id, "role": role.id, "active": user.is_active},
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
        await self.session.execute(
            delete(MemberFavorite).where(MemberFavorite.user_id == user_id)
        )
        # Remembered sessions are removed by their cascading foreign key.
        await self.session.delete(user)
        await self.session.commit()
        log_security_event("member_removed", actor.email, {"member_id": user_id})

    async def list_roles(self) -> list[RoleProfile]:
        holders = dict(
            (
                await self.session.execute(
                    select(User.role, func.count()).group_by(User.role)
                )
            ).all()
        )
        roles = await self.session.scalars(
            select(MemberRole).order_by(MemberRole.created_at, MemberRole.id)
        )
        return [self._role_profile(role, holders.get(role.id, 0)) for role in roles]

    async def create_role(self, change: RoleCreate, actor: User) -> RoleProfile:
        await self._lock_membership(actor)
        await self._ensure_unique_name(change.name)
        base = _role_id(change.name)
        role_id, suffix = base, 2
        while await self.session.get(MemberRole, role_id) is not None:
            role_id, suffix = f"{base[:36]}-{suffix}", suffix + 1
        role = MemberRole(
            id=role_id,
            name=change.name,
            permissions=[p.value for p in known_permissions(change.permissions)],
        )
        self.session.add(role)
        await self.session.commit()
        await self.session.refresh(role)
        log_security_event(
            "member_role_created",
            actor.email,
            {"role": role.id, "permissions": role.permissions},
        )
        return self._role_profile(role, 0)

    async def update_role(
        self, role_id: str, change: RoleUpdate, actor: User
    ) -> RoleProfile:
        await self._lock_membership(actor)
        role = await self.session.get(
            MemberRole, role_id, with_for_update=True, populate_existing=True
        )
        if role is None:
            raise NotFoundError("Role not found")
        if role.id == ADMIN_ROLE:
            raise ConflictError("The administrator role always holds every permission")
        if change.name is not None and change.name != role.name:
            await self._ensure_unique_name(change.name, role.id)
            role.name = change.name
        if change.permissions is not None:
            role.permissions = [p.value for p in known_permissions(change.permissions)]
        await self._commit_keeping_a_manager()
        await self.session.refresh(role)
        log_security_event(
            "member_role_changed",
            actor.email,
            {"role": role.id, "permissions": role.permissions},
        )
        return self._role_profile(role, await self._holders(role.id))

    async def delete_role(self, role_id: str, actor: User) -> None:
        await self._lock_membership(actor)
        role = await self.session.get(
            MemberRole, role_id, with_for_update=True, populate_existing=True
        )
        if role is None:
            raise NotFoundError("Role not found")
        if role.id in BUILT_IN_ROLES:
            raise ConflictError("Built-in roles cannot be deleted")
        if holders := await self._holders(role.id):
            raise ConflictError(
                f"{holders} member{'s' if holders != 1 else ''} still "
                f"{'hold' if holders != 1 else 'holds'} this role; "
                "give them another role first"
            )
        await self.session.delete(role)
        await self.session.commit()
        log_security_event("member_role_deleted", actor.email, {"role": role_id})

    async def _holders(self, role_id: str) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).select_from(User).where(User.role == role_id)
            )
            or 0
        )

    async def _ensure_unique_name(self, name: str, role_id: str = "") -> None:
        clash = await self.session.scalar(
            select(MemberRole.id).where(
                func.lower(MemberRole.name) == name.lower(), MemberRole.id != role_id
            )
        )
        if clash is not None:
            raise ConflictError("Another role already has this name")

    @staticmethod
    def _role_profile(role: MemberRole, members: int) -> RoleProfile:
        return RoleProfile(
            id=role.id,
            name=role.name,
            permissions=role_permissions(role.id, role.permissions),
            editable=role.id != ADMIN_ROLE,
            built_in=role.id in BUILT_IN_ROLES,
            members=members,
        )

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
        user.hashed_password = _hash_password(password)
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
        user.hashed_password = _hash_password(password)
        user.reset_token_hash = None
        user.reset_token_expires_at = None
        user.session_version += 1
        await self.session.commit()
        log_security_event("password_reset_success", user.email, {"member_id": user.id})
