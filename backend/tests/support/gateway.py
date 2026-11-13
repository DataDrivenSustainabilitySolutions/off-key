"""The public gateway's /v1 routes mounted as production mounts them."""

import inspect
from datetime import UTC, datetime
from typing import Any, NamedTuple

from fastapi import FastAPI, HTTPException
from off_key_api_gateway.api import access
from off_key_api_gateway.api.rate_limiter import limiter, rate_limit_exceeded_handler
from off_key_api_gateway.api.v1 import routes
from off_key_api_gateway.facades.tactic import TacticError
from off_key_core.auth.agents import new_agent_key
from off_key_core.auth.permissions import role_permissions
from off_key_core.schemas.members import MemberProfile
from pydantic import BaseModel
from slowapi.errors import RateLimitExceeded

AGENT_KEY = new_agent_key()
BY_KEY = {"Authorization": f"Bearer {AGENT_KEY}"}
BY_MEMBER = {"Authorization": "Bearer member"}


def member_profile(role: str = "user", **fields) -> MemberProfile:
    """A signed-in member; built-in roles carry their permissions."""
    return MemberProfile(
        **{
            "id": 17,
            "email": f"{role}@example.com",
            "role": role,
            "permissions": role_permissions(role, ()),
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
        app.dependency_overrides[access.current_caller] = lambda: member
    limiter.reset()
    return app


def agent_profile(**fields) -> dict:
    """What TACTIC says of the agent that holds ``AGENT_KEY``."""
    return {
        "id": 4,
        "name": "Designer",
        "key_hint": AGENT_KEY[-4:],
        "may_start": False,
        "created_by": "admin@example.com",
        "created_at": datetime.now(UTC).isoformat(),
    } | fields


class Asked(NamedTuple):
    """One request that reached TACTIC."""

    method: str
    endpoint: str
    headers: dict[str, str]
    body: Any
    params: Any


class StandInTactic:
    """TACTIC as the gateway sees it, for as long as the test runs.

    It knows the agent that holds ``AGENT_KEY`` and, where given, the member
    behind ``BY_MEMBER``. Everything else it answers from ``answers``, by
    method and endpoint, or else with ``otherwise``. An answer may be a
    function of the request, and one that raises an ``HTTPException`` refuses
    as TACTIC would. It keeps what it was asked.
    """

    def __init__(
        self, monkeypatch, profile: dict, member=None, answers=None, otherwise=None
    ):
        self.profile = profile
        self.member = member
        self.answers = answers or {}
        self.otherwise = {} if otherwise is None else otherwise
        self.asked: list[Asked] = []
        monkeypatch.setattr(access.tactic, "request", self.request)

    async def request(
        self, method, endpoint, json_data=None, params=None, headers=None, **_
    ):
        asked = Asked(method, endpoint, headers or {}, json_data, params)
        self.asked.append(asked)
        authorization = asked.headers.get("Authorization")
        if endpoint == "/api/v1/agents/me":
            if authorization != BY_KEY["Authorization"]:
                raise TacticError("This key is not valid", status=401)
            return self.profile
        if endpoint == "/api/v1/members/me":
            if self.member is None or authorization != BY_MEMBER["Authorization"]:
                raise TacticError("Invalid access token", status=401)
            return self.member.model_dump(mode="json")
        answer = self.answers.get((method, endpoint), self.otherwise)
        if callable(answer):
            try:
                answer = answer(asked)
                if inspect.isawaitable(answer):
                    answer = await answer
            except HTTPException as refusal:
                raise TacticError(
                    str(refusal.detail),
                    status=refusal.status_code,
                    body={"detail": refusal.detail},
                ) from refusal
        if isinstance(answer, BaseModel):
            return answer.model_dump(mode="json")
        return answer

    def forwarded(self) -> list[Asked]:
        """What reached TACTIC beyond asking who is calling."""
        return [asked for asked in self.asked if not asked.endpoint.endswith("/me")]

    def last(self, method: str, endpoint: str) -> Asked:
        """The latest request of that kind."""
        return next(
            asked
            for asked in reversed(self.asked)
            if (asked.method, asked.endpoint) == (method, endpoint)
        )
