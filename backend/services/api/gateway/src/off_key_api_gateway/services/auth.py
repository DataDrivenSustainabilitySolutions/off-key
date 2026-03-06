from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from off_key_core.config.auth import get_auth_settings

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_REQUIRED_SCOPED_CLAIMS = ("sub", "exp", "iss", "aud", "token_type")


def get_password_hash(password: str) -> str:
    return password_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_context.verify(plain_password, hashed_password)


def create_jwt(data: dict, expires_delta: timedelta = None) -> str:
    settings = get_auth_settings()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
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


def create_verification_token(email: str, expires_minutes: int = 120) -> str:
    settings = get_auth_settings()
    to_encode = {
        "sub": email,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_minutes),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "token_type": "email_verification",
    }
    return jwt.encode(
        to_encode,
        settings.JWT_VERIFICATION_SECRET.get_secret_value(),
        algorithm=settings.ALGORITHM,
    )


def _decode_scoped_token(token: str, expected_token_type: str) -> str | None:
    settings = get_auth_settings()
    try:
        payload = jwt.decode(
            token,
            settings.JWT_VERIFICATION_SECRET.get_secret_value(),
            algorithms=[settings.ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={"leeway": settings.JWT_CLOCK_SKEW_SECONDS},
        )
        if any(claim not in payload for claim in _REQUIRED_SCOPED_CLAIMS):
            return None
        if payload.get("token_type") != expected_token_type:
            return None
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            return None
        return subject
    except JWTError:
        return None


def verify_verification_token(token: str) -> str | None:
    return _decode_scoped_token(token, expected_token_type="email_verification")


def create_reset_token(email: str, expires_minutes: int = 120) -> str:
    settings = get_auth_settings()
    to_encode = {
        "sub": email,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_minutes),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "token_type": "password_reset",
    }
    return jwt.encode(
        to_encode,
        settings.JWT_VERIFICATION_SECRET.get_secret_value(),
        algorithm=settings.ALGORITHM,
    )


def verify_reset_token(token: str) -> str | None:
    return _decode_scoped_token(token, expected_token_type="password_reset")
