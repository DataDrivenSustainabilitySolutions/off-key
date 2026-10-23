"""Use cases for user/account/auth operations."""

import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain import AuthenticationError
from ...repositories import UserRepository

# Matches the work factor of hashes created by bcrypt.gensalt().
_DUMMY_HASH = bcrypt.hashpw(b"off-key-timing-equalizer", bcrypt.gensalt()).decode()


class UserService:
    """Application-level user/account use cases."""

    def __init__(self, session: AsyncSession, repository: UserRepository):
        self._session = session
        self._repository = repository

    async def authenticate(self, *, email: str, password: str) -> dict[str, object]:
        user = await self._repository.get_by_email(email=email)
        hashed_password = (user.hashed_password or "") if user else ""
        # Unknown and not-yet-activated accounts still pay the full bcrypt cost,
        # so response time does not reveal which emails are registered.
        has_hash = hashed_password.startswith("$2")
        try:
            credentials_valid = bcrypt.checkpw(
                password.encode("utf-8"),
                (hashed_password if has_hash else _DUMMY_HASH).encode("utf-8"),
            )
        except ValueError:
            credentials_valid = False

        if user is None or not has_hash or not credentials_valid:
            raise AuthenticationError("Invalid credentials")

        if not user.is_active:
            raise AuthenticationError("Invalid credentials")

        if not user.is_verified:
            raise AuthenticationError("Email not verified")

        role = user.role.value if hasattr(user.role, "value") else str(user.role)
        return {
            "id": user.id,
            "email": user.email,
            "role": role,
            "session_version": user.session_version,
        }
