from datetime import UTC, datetime, timedelta

from jose import jwt
from off_key_core.config.auth import get_auth_settings


def create_jwt(data: dict, expires_delta: timedelta | None = None) -> str:
    settings = get_auth_settings()
    to_encode = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta
        if expires_delta
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update(
        {
            "exp": expire,
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
        }
    )
    return jwt.encode(
        to_encode,
        settings.JWT_SECRET.get_secret_value(),
        algorithm=settings.ALGORITHM,
    )
