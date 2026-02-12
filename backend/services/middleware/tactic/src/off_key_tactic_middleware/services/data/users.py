"""Use cases for user/account/auth operations."""

import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession

from off_key_core.config.logs import logger
from off_key_core.db.models import User
from off_key_core.utils.enum import RoleEnum

from ...domain import (
    AuthenticationError,
    ConflictError,
    InfrastructureError,
    NotFoundError,
    ValidationError,
)
from ...repositories import UserRepository
from ...schemas import UserCreateRequest


class UserService:
    """Application-level user/account use cases."""

    def __init__(self, session: AsyncSession, repository: UserRepository):
        self._session = session
        self._repository = repository

    async def authenticate(self, *, email: str, password: str) -> dict[str, str]:
        user = await self._repository.get_by_email(email=email)
        if user is None:
            raise AuthenticationError("Invalid credentials")

        hashed_password = user.hashed_password or ""
        try:
            credentials_valid = bcrypt.checkpw(
                password.encode("utf-8"),
                hashed_password.encode("utf-8"),
            )
        except ValueError:
            credentials_valid = False

        if not credentials_valid:
            raise AuthenticationError("Invalid credentials")

        if not user.is_verified:
            raise AuthenticationError("Email not verified")

        role = user.role.value if hasattr(user.role, "value") else str(user.role)
        return {"email": user.email, "role": role}

    async def get_by_email(self, *, email: str) -> dict[str, object]:
        user = await self._repository.get_by_email(email=email)
        if user is None:
            raise NotFoundError("User not found")

        role = user.role.value if hasattr(user.role, "value") else str(user.role)
        return {
            "id": user.id,
            "email": user.email,
            "is_verified": user.is_verified,
            "role": role,
            "updated_at": user.updated_at,
            "created_at": user.created_at,
        }

    async def create_user(self, *, payload: UserCreateRequest) -> User:
        existing = await self._repository.get_by_email(email=payload.email)
        if existing is not None:
            raise ConflictError("Email already registered")

        role = payload.role
        if isinstance(role, str):
            try:
                role = RoleEnum(role)
            except ValueError as exc:
                raise ValidationError(f"Invalid role: {role}") from exc

        user = User(
            email=payload.email,
            hashed_password=payload.hashed_password,
            verification_token=payload.verification_token,
            role=role,
        )

        try:
            created = await self._repository.add(user)
            await self._session.commit()
            logger.info(f"Created new user: {payload.email}")
            return created
        except Exception as exc:
            await self._session.rollback()
            raise InfrastructureError(f"Failed to create user: {exc}") from exc

    async def verify_email(self, *, email: str) -> dict[str, str]:
        user = await self._repository.get_by_email(email=email)
        if user is None:
            raise NotFoundError("User not found")

        user.is_verified = True
        user.verification_token = None

        try:
            await self._session.commit()
        except Exception as exc:
            await self._session.rollback()
            raise InfrastructureError(f"Failed to verify user: {exc}") from exc

        logger.info(f"Verified email for user: {email}")
        return {"message": "Email verified successfully"}

    async def update_password(
        self,
        *,
        email: str,
        new_password_hash: str,
    ) -> dict[str, str]:
        user = await self._repository.get_by_email(email=email)
        if user is None:
            raise NotFoundError("User not found")

        user.hashed_password = new_password_hash
        try:
            await self._session.commit()
        except Exception as exc:
            await self._session.rollback()
            raise InfrastructureError(f"Failed to update password: {exc}") from exc

        logger.info(f"Updated password for user: {email}")
        return {"message": "Password updated successfully"}
