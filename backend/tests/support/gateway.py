"""The API's /v1 routes mounted as production mounts them."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from fastapi import FastAPI
from off_key_api_gateway.api import access
from off_key_api_gateway.api.rate_limiter import limiter, rate_limit_exceeded_handler
from off_key_api_gateway.api.v1 import routes
from off_key_api_gateway.app import deployment_in_progress
from off_key_core.auth.agents import new_agent_key
from off_key_core.auth.permissions import role_permissions
from off_key_core.db.base import get_db_async
from off_key_core.db.maintenance import DeploymentInProgressError
from off_key_core.db.models import Agent, MemberRole, User
from slowapi.errors import RateLimitExceeded

AGENT_KEY = new_agent_key()
BY_KEY = {"Authorization": f"Bearer {AGENT_KEY}"}
BY_MEMBER = {"Authorization": "Bearer member"}


def member(role: str = "user", *, permissions=None, **fields) -> User:
    """A signed-in member; built-in roles carry their permissions.

    ``permissions`` gives a custom role what it holds.
    """
    if permissions is None:
        permissions = role_permissions(role, ())
    granted = [str(permission) for permission in permissions]
    values = {
        "id": 17,
        "email": f"{role}@example.com",
        "role": role,
        "is_active": True,
        "is_verified": True,
        "session_version": 0,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    } | fields
    return User(
        **values,
        member_role=MemberRole(
            id=values["role"], name=values["role"], permissions=granted
        ),
    )


def agent(**fields) -> Agent:
    """The agent that holds ``AGENT_KEY``."""
    return Agent(
        **{
            "id": 4,
            "name": "Designer",
            "key_hint": AGENT_KEY[-4:],
            "starts": "nothing",
            "created_by": "admin@example.com",
            "created_at": datetime.now(UTC),
        }
        | fields
    )


def gateway_app(
    caller: User | Agent | None = None,
    *,
    session=None,
    sessions=None,
    overrides: dict | None = None,
) -> FastAPI:
    """The /v1 router with the API's limiter.

    ``caller`` skips the token check; ``session`` stands in for the database,
    or ``sessions`` opens a real session per request and commits it as the
    API does; ``overrides`` replaces providers with fakes.
    """
    app = FastAPI()
    app.include_router(routes.router, prefix="/v1")
    app.state.limiter = limiter
    app.state.system_live = None
    app.state.broker_check = None
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.add_exception_handler(DeploymentInProgressError, deployment_in_progress)
    if sessions is not None:

        async def per_request():
            async with sessions() as opened:
                yield opened
                await opened.commit()

        app.dependency_overrides[get_db_async] = per_request
    else:
        database = AsyncMock() if session is None else session
        app.dependency_overrides[get_db_async] = lambda: database
    if caller is not None:
        app.dependency_overrides[access.current_caller] = lambda: caller
    for dependency, value in (overrides or {}).items():
        app.dependency_overrides[dependency] = value
    limiter.reset()
    return app


def returning(value):
    """A provider override that hands out ``value``.

    A default argument would become a query parameter whose default FastAPI
    copies, so the override closes over the value instead.
    """
    return lambda: value


class Callers:
    """Who the API finds behind a credential, for as long as the test runs.

    The key ``AGENT_KEY`` names ``agent``, ``BY_MEMBER`` names ``member``; any
    other credential names nobody. The checks around the lookup stay real: a
    key is still refused where a route is not open to it.
    """

    def __init__(self, monkeypatch, *, agent: Agent | None = None, member=None):
        self.agent = agent
        self.member = member
        monkeypatch.setattr(access, "agent_by_key", self.agent_by_key)
        monkeypatch.setattr(access, "signed_in_member", self.signed_in_member)

    async def agent_by_key(self, key, session):
        return self.agent if key == AGENT_KEY else None

    async def signed_in_member(self, token, session):
        from fastapi import HTTPException

        if self.member is None or token != BY_MEMBER["Authorization"].split()[1]:
            raise HTTPException(401, "Invalid access token")
        return self.member
