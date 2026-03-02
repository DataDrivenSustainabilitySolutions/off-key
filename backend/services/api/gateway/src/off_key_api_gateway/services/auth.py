from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from off_key_core.config.auth import get_auth_settings

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


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
    to_encode.update({"exp": expire})
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
        "token_type": "email_verification",
    }
    return jwt.encode(
        to_encode,
        settings.JWT_VERIFICATION_SECRET.get_secret_value(),
        algorithm=settings.ALGORITHM,
    )


def verify_verification_token(token: str) -> str | None:
    settings = get_auth_settings()
    try:
        payload = jwt.decode(
            token,
            settings.JWT_VERIFICATION_SECRET.get_secret_value(),
            algorithms=[settings.ALGORITHM],
        )
        return payload.get("sub")
    except JWTError:
        return None


def create_reset_token(email: str, expires_minutes: int = 120) -> str:
    settings = get_auth_settings()
    to_encode = {
        "sub": email,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_minutes),
        "token_type": "password_reset",
    }
    return jwt.encode(
        to_encode,
        settings.JWT_VERIFICATION_SECRET.get_secret_value(),
        algorithm=settings.ALGORITHM,
    )
