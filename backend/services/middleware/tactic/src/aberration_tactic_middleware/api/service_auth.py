import secrets

from aberration_core.config.service_auth import get_service_auth_settings
from fastapi import Header, HTTPException


def require_gateway(
    x_aberration_service_key: str | None = Header(default=None),
) -> None:
    expected = get_service_auth_settings().INTERNAL_API_SECRET.get_secret_value()
    if x_aberration_service_key is None or not secrets.compare_digest(
        x_aberration_service_key.encode(), expected.encode()
    ):
        raise HTTPException(401, "Gateway authentication required")
