import secrets

from fastapi import Header, HTTPException
from off_key_core.config.service_auth import get_service_auth_settings


def require_gateway(x_off_key_service_key: str | None = Header(default=None)) -> None:
    expected = get_service_auth_settings().INTERNAL_API_SECRET.get_secret_value()
    if x_off_key_service_key is None or not secrets.compare_digest(
        x_off_key_service_key.encode(), expected.encode()
    ):
        raise HTTPException(401, "Gateway authentication required")
