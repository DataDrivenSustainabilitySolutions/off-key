"""The access-token claim contract: the gateway issues, TACTIC decodes.

Needs the ``auth`` extra (python-jose).
"""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Annotated, Literal
from uuid import uuid4

from jose import JWTError, jwt
from jose.utils import base64url_decode
from pydantic import BaseModel, Field, StrictInt, ValidationError

from off_key_core.config.auth import get_auth_settings


class AccessClaims(BaseModel):
    """Identity claims of an access token; bools, strings and floats are refused."""

    sub: str
    user_id: Annotated[StrictInt, Field(gt=0)]
    session_version: Annotated[StrictInt, Field(ge=0)]
    session_family: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    # Account links and other token types carry a token_type; access tokens do not.
    token_type: None = None


class InvalidAccessToken(Exception):
    """``kind`` is "token" for a bad signature or lifetime, "claims" otherwise."""

    def __init__(self, kind: Literal["token", "claims"]):
        super().__init__(kind)
        self.kind = kind


def issue_access_token(
    claims: AccessClaims, expires_delta: timedelta | None = None
) -> str:
    settings = get_auth_settings()
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return jwt.encode(
        claims.model_dump(exclude_none=True)
        | {
            "exp": expire,
            "jti": uuid4().hex,
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
        },
        settings.JWT_SECRET.get_secret_value(),
        algorithm=settings.ALGORITHM,
    )


def decode_access_token(token: str) -> AccessClaims:
    return decode_access_token_with_expiry(token)[0]


def access_token_digest(token: str) -> str:
    """Identify a verified JWT across equivalent signature base64 encodings.

    The signature authenticates the exact header/payload bytes. Its own base64
    padding and unused bits are not authenticated, so hash the decoded signature.
    Call only after decode_access_token has accepted the token.
    """
    signed, _, signature = token.rpartition(".")
    return sha256(
        signed.encode() + b"." + base64url_decode(signature.encode())
    ).hexdigest()


def decode_access_token_with_expiry(token: str) -> tuple[AccessClaims, datetime]:
    settings = get_auth_settings()
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET.get_secret_value(),
            algorithms=[settings.ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={
                "require_exp": True,
                "require_sub": True,
                "require_iss": True,
                "require_aud": True,
                "leeway": settings.JWT_CLOCK_SKEW_SECONDS,
            },
        )
    except JWTError as exc:
        raise InvalidAccessToken("token") from exc
    try:
        claims = AccessClaims.model_validate(
            {key: payload.get(key) for key in AccessClaims.model_fields}
        )
        # python-jose accepts the whole second at exp + leeway (integer now).
        # Keep revocations until that inclusive final second has ended.
        deadline = datetime.fromtimestamp(int(payload["exp"]), UTC) + timedelta(
            seconds=settings.JWT_CLOCK_SKEW_SECONDS + 1
        )
        return claims, deadline
    except (ValidationError, ValueError, OverflowError, OSError) as exc:
        raise InvalidAccessToken("claims") from exc
