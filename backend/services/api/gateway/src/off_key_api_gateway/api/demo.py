"""Public read-only demo.

With ``DEMO_MODE`` on, a request without an ``Authorization`` header is a
guest. A guest reaches only the routes in ``GUEST_ROUTES``; the gateway signs
those requests in as one ordinary viewer member, so TACTIC still applies the
member role to every call. Anything else answers 403, including routes added
later, until they are listed here. Requests that carry a token are untouched.
"""

import asyncio
import json
import re
import time

from fastapi import APIRouter
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from off_key_core.config.auth import get_auth_settings
from off_key_core.config.logs import logger
from off_key_core.utils.enum import RoleEnum
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..facades.tactic import TacticError, tactic
from ..settings import DemoSettings
from .rate_limiter import client_ip
from .v1.auth import access_token_response

# Read routes a guest may call, as OpenAPI path templates. Writes, member
# administration, favorites changes, live previews and the system revision log
# (it names the members who saved) stay closed.
GUEST_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/v1/members/me"),
        ("GET", "/v1/chargers/available"),
        ("GET", "/v1/chargers/active"),
        ("GET", "/v1/chargers/active/id"),
        ("GET", "/v1/telemetry/{charger_id}/type"),
        ("GET", "/v1/telemetry/{charger_id}/data"),
        ("GET", "/v1/favorites"),
        ("GET", "/v1/anomalies"),
        ("GET", "/v1/anomalies/count"),
        ("GET", "/v1/monitors"),
        ("GET", "/v1/monitors/all"),
        ("GET", "/v1/monitors/models"),
        ("GET", "/v1/monitors/evidence"),
        ("GET", "/v1/monitors/evidence/chart"),
        ("GET", "/v1/monitors/workspace"),
        ("GET", "/v1/monitors/pipelines"),
        ("GET", "/v1/monitors/pipelines/catalog"),
        ("GET", "/v1/monitors/pipelines/{pipeline_id}"),
        ("GET", "/v1/monitors/pipelines/{pipeline_id}/revisions"),
        ("GET", "/v1/monitors/pipelines/{pipeline_id}/revisions/{revision_id}"),
        (
            "GET",
            "/v1/monitors/pipelines/{pipeline_id}/revisions/{revision_id}/metadata",
        ),
        ("GET", "/v1/monitors/pipeline-activations/{activation_id}"),
        ("GET", "/v1/monitors/{service_id}/pipeline"),
        ("GET", "/v1/monitors/{service_id}/pipeline-history"),
        ("GET", "/v1/monitors/{service_id}/pipeline-metadata"),
        ("GET", "/v1/monitors/{service_id}/pipeline-state"),
        ("GET", "/v1/system"),
        ("GET", "/v1/system/health"),
        ("GET", "/v1/system/storage"),
        ("GET", "/v1/system/live"),
        # A read that sends the stream ids in its body.
        ("POST", "/v1/system/collection/status"),
    }
)
# Sign-in, account links and this endpoint behave as without the demo.
OPEN_PREFIXES = ("/v1/auth/", "/v1/demo")
READ_ONLY = "This public demo is read-only. Sign in to make changes."
UNAVAILABLE = "The public demo is unavailable right now. Please try again later."
# Renew the viewer token this long before it expires.
RENEW_SECONDS = 60


def _template_pattern(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[^}]+\})", template)
    return re.compile(
        "".join("[^/]+" if part.startswith("{") else re.escape(part) for part in parts)
    )


GUEST_PATTERNS = tuple(
    (method, _template_pattern(template)) for method, template in GUEST_ROUTES
)


def guest_may_call(method: str, path: str) -> bool:
    if method == "HEAD":
        method = "GET"
    return any(
        method == allowed and pattern.fullmatch(path)
        for allowed, pattern in GUEST_PATTERNS
    )


class DemoUnavailable(Exception):
    """The viewer account cannot sign in; guests get 503 meanwhile."""


class DemoViewer:
    """One cached access token for the viewer member that guests browse as."""

    def __init__(self, settings: DemoSettings):
        self._settings = settings
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    def invalidate(self, token: str) -> None:
        if self._token == token:
            self._token = None

    async def token(self) -> str:
        if self._token and time.monotonic() < self._expires_at:
            return self._token
        async with self._lock:
            if self._token and time.monotonic() < self._expires_at:
                return self._token
            self._token, lifetime = await self._sign_in()
            self._expires_at = time.monotonic() + max(lifetime - RENEW_SECONDS, 1)
            return self._token

    async def _sign_in(self) -> tuple[str, float]:
        email, password = (
            self._settings.DEMO_VIEWER_EMAIL,
            self._settings.DEMO_VIEWER_PASSWORD,
        )
        if email is None or password is None:
            raise DemoUnavailable
        try:
            viewer = await tactic.authenticate_user(
                email=str(email), password=password.get_secret_value()
            )
        except TacticError as exc:
            logger.error("event=demo.viewer_sign_in_failed status=%s", exc.status)
            raise DemoUnavailable from exc
        # Guests must never act with more than member rights.
        if viewer.get("role") != RoleEnum.user:
            logger.error("event=demo.viewer_role_refused")
            raise DemoUnavailable
        token = access_token_response(viewer)["access_token"]
        return token, get_auth_settings().ACCESS_TOKEN_EXPIRE_MINUTES * 60


class DemoGuestMiddleware:
    """Admit anonymous reads on the allowlist; refuse every other anonymous call."""

    def __init__(self, app: ASGIApp, settings: DemoSettings):
        self.app = app
        self.viewer = DemoViewer(settings)
        self.limit = parse(f"{settings.DEMO_GUEST_REQUESTS_PER_MINUTE}/minute")
        self.limiter = MovingWindowRateLimiter(MemoryStorage())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._anonymous(scope):
            await self.app(scope, receive, send)
            return
        method, path = scope["method"], scope["path"]
        if method == "OPTIONS" or path.startswith(OPEN_PREFIXES):
            await self.app(scope, receive, send)
            return
        if not path.startswith("/v1/"):
            await self.app(scope, receive, send)
            return
        if not guest_may_call(method, path):
            await _reply(send, 403, READ_ONLY)
            return
        if not self.limiter.hit(self.limit, "demo-guest", client_ip(Request(scope))):
            await _reply(send, 429, "Too many requests. Please slow down.")
            return
        try:
            token = await self.viewer.token()
        except DemoUnavailable:
            await _reply(send, 503, UNAVAILABLE)
            return
        headers = [
            *scope["headers"],
            (b"authorization", f"Bearer {token}".encode()),
        ]
        state = {**scope.get("state", {}), "demo_guest": True}
        guest_scope = {**scope, "headers": headers, "state": state}

        async def guest_send(message: Message) -> None:
            # A revoked viewer session signs in again on the next request.
            if message["type"] == "http.response.start" and message["status"] == 401:
                self.viewer.invalidate(token)
            await send(message)

        await self.app(guest_scope, receive, guest_send)

    @staticmethod
    def _anonymous(scope: Scope) -> bool:
        return not any(name == b"authorization" for name, _ in scope["headers"])


async def _reply(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


router = APIRouter()


@router.get("")
async def demo_status(request: Request) -> dict[str, bool]:
    """Tell the browser whether signed-out visitors browse as guests."""
    return {"enabled": getattr(request.app.state, "demo_enabled", False)}
