"""Public read-only demo.

With ``DEMO_MODE`` on, a request without an ``Authorization`` header is a
guest. A guest reaches only the routes in ``GUEST_ROUTES``; the API signs
those requests in as one ordinary viewer member, so the member role still
applies to every call. Anything else answers 403, including routes added
later, until they are listed here. Requests that carry a token are untouched.
"""

import asyncio
import json
import re
import time

from fastapi import APIRouter, Response
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from off_key_core.auth.demo import DEMO_VIEWER_ROLE
from off_key_core.config.auth import get_auth_settings
from off_key_core.config.logs import logger
from off_key_core.db.base import get_async_session_local
from off_key_core.demo.sources import public_sources
from off_key_tactic_middleware.domain import AuthenticationError
from off_key_tactic_middleware.repositories import UserRepository
from off_key_tactic_middleware.services.accounts.users import UserService
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..settings import DemoSettings
from .rate_limiter import client_ip
from .request_guards import route_path
from .v1.auth import access_token_response

# Read routes a guest may call, as OpenAPI path templates. Writes, member
# administration, favorites changes, live previews and the system revision log
# (it names the members who saved) stay closed.
GUEST_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/v1/devices"),
        ("GET", "/v1/devices/{device_id}/readings"),
        ("GET", "/v1/readings/{reading_id}/measurements"),
        ("GET", "/v1/readings/{reading_id}/measurements/buckets"),
        ("GET", "/v1/readings/{reading_id}/profile"),
        ("GET", "/v1/monitors/overview"),
        ("GET", "/v1/monitors"),
        ("GET", "/v1/monitors/{monitor_id}"),
        ("GET", "/v1/monitors/{monitor_id}/pipeline"),
        ("GET", "/v1/monitors/{monitor_id}/pipeline/history"),
        ("GET", "/v1/monitors/{monitor_id}/pipeline/timeline"),
        ("GET", "/v1/monitors/{monitor_id}/pipeline/metadata"),
        ("GET", "/v1/monitors/{monitor_id}/pipeline/state"),
        ("GET", "/v1/pipelines"),
        ("GET", "/v1/pipelines/{pipeline_id}"),
        ("GET", "/v1/pipelines/{pipeline_id}/revisions"),
        ("GET", "/v1/pipelines/{pipeline_id}/revisions/{revision_id}"),
        ("GET", "/v1/pipelines/{pipeline_id}/revisions/{revision_id}/metadata"),
        ("GET", "/v1/pipeline-components"),
        ("GET", "/v1/pipeline-components/search"),
        ("GET", "/v1/pipeline-components/{component_id}"),
        # What agents proposed, with member emails hidden (see pipelines.py).
        ("GET", "/v1/pipeline-proposals"),
        ("GET", "/v1/pipeline-proposals/{proposal_id}"),
        ("GET", "/v1/pipeline-blocks"),
        ("GET", "/v1/forecast-models"),
        ("GET", "/v1/pipeline-activations/{activation_id}"),
        ("GET", "/v1/detectors"),
        ("GET", "/v1/evidence"),
        ("GET", "/v1/evidence/chart"),
        ("GET", "/v1/alarms"),
        ("GET", "/v1/alarms/count"),
        ("GET", "/v1/alarms/{alarm_id}"),
        ("GET", "/v1/catalogue"),
        ("GET", "/v1/recording/health"),
        ("GET", "/v1/storage"),
        ("GET", "/v1/dojo/datasets"),
        ("GET", "/v1/dojo/datasets/{dataset_id}"),
        ("GET", "/v1/dojo/datasets/{dataset_id}/series/{series_id}/points"),
        ("GET", "/v1/dojo/datasets/{dataset_id}/labels"),
        ("GET", "/v1/dojo/datasets/{dataset_id}/comparison"),
        ("GET", "/v1/dojo/runs"),
        ("GET", "/v1/dojo/runs/{run_id}"),
        ("GET", "/v1/dojo/runs/{run_id}/metrics"),
        ("GET", "/v1/dojo/runs/{run_id}/calibration"),
        ("GET", "/v1/dojo/runs/{run_id}/outline"),
        ("GET", "/v1/dojo/runs/{run_id}/steps"),
        ("GET", "/v1/dojo/runs/{run_id}/results"),
        ("POST", "/v1/recording/status"),
        ("POST", "/v1/alarms/query"),
    }
)
# Sign-in, account links and this endpoint behave as without the demo.
OPEN_PREFIXES = ("/v1/auth/",)
OPEN_PATHS = {"/v1/demo"}
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
        self._retry_at = 0.0

    def invalidate(self, token: str) -> None:
        if self._token == token:
            self._token = None

    async def token(self) -> str:
        if self._token and time.monotonic() < self._expires_at:
            return self._token
        async with self._lock:
            if self._token and time.monotonic() < self._expires_at:
                return self._token
            if time.monotonic() < self._retry_at:
                raise DemoUnavailable
            try:
                self._token, lifetime = await self._sign_in()
            except DemoUnavailable:
                self._retry_at = time.monotonic() + 10
                raise
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
            async with get_async_session_local()() as session:
                viewer = await UserService(
                    session, UserRepository(session)
                ).authenticate(email=str(email), password=password.get_secret_value())
        except (AuthenticationError, SQLAlchemyError, OSError) as exc:
            logger.error(
                "event=demo.viewer_sign_in_failed error_type=%s", type(exc).__name__
            )
            raise DemoUnavailable from exc
        # The dedicated role is checked again, with its permissions, on every read.
        if viewer.get("role") != DEMO_VIEWER_ROLE:
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
        # Behind the dashboard the gateway runs with --root-path /api, and the
        # path a guest is judged by is the one the routes see, without it.
        method, path = scope["method"], route_path(scope)
        if (
            method == "OPTIONS"
            or path.startswith(OPEN_PREFIXES)
            or path in OPEN_PATHS
            or not path.startswith("/v1/")
        ):
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
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        (key, value)
                        for key, value in message["headers"]
                        if key.lower() not in {b"cache-control", b"set-cookie"}
                    ]
                    + [(b"cache-control", b"no-store")],
                }
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
async def demo_status(request: Request, response: Response) -> dict:
    """Tell the browser whether signed-out visitors browse as guests."""
    enabled = getattr(request.app.state, "demo_enabled", False)
    response.headers["Cache-Control"] = "no-store"
    return {"enabled": enabled, "sources": public_sources() if enabled else []}
