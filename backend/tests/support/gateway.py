"""The public gateway's /v1 routes mounted as production mounts them."""

from datetime import UTC, datetime

from fastapi import FastAPI
from off_key_api_gateway.api import access
from off_key_api_gateway.api.rate_limiter import limiter, rate_limit_exceeded_handler
from off_key_api_gateway.api.v1 import routes
from off_key_core.schemas.members import MemberProfile
from slowapi.errors import RateLimitExceeded


def member_profile(role: str = "user", **fields) -> MemberProfile:
    return MemberProfile(
        **{
            "id": 17,
            "email": f"{role}@example.com",
            "role": role,
            "is_active": True,
            "is_verified": True,
            "created_at": datetime.now(UTC),
        }
        | fields
    )


def gateway_app(member: MemberProfile | None = None) -> FastAPI:
    """The /v1 router with the gateway's limiter; `member` skips token checks."""
    app = FastAPI()
    app.include_router(routes.router, prefix="/v1")
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    if member is not None:
        app.dependency_overrides[access.current_member] = lambda: member
    limiter.reset()
    return app
