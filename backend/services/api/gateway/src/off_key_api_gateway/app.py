"""Compose the API gateway application."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from off_key_core.api_docs import router as api_docs_router
from off_key_core.config.auth import get_auth_settings
from off_key_core.config.bootstrap import start_service
from off_key_core.config.email import get_email_settings
from off_key_core.config.logs import (
    CorrelationIdMiddleware,
    logger,
)
from off_key_core.config.runtime import get_runtime_settings
from off_key_core.config.service_auth import get_service_auth_settings
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.gzip import GZipMiddleware

from off_key_api_gateway.settings import (
    AppSettings,
    DemoSettings,
    get_app_settings,
    get_service_endpoints_settings,
)

from .api.demo import DemoGuestMiddleware
from .api.mcp_server import add_mcp
from .api.middleware import RequestLoggingMiddleware
from .api.rate_limiter import limiter, rate_limit_exceeded_handler
from .api.request_guards import BodySizeLimitMiddleware, ClientRateLimitMiddleware
from .api.v1.routes import router as v1_router
from .facades.tactic import tactic

API_DESCRIPTION = """\
The gateway API of one Aberration installation: its MQTT sources, the readings
it records, the monitors that watch them and the alarms they raise. The web app
uses this same API, so every change it makes can be made here.

**Base URL.** Behind the dashboard the API lives under `/api`, which the
`servers` entry of this document states: `/v1/alarms` is called as
`https://<dashboard>/api/v1/alarms`.

**Authentication.** `POST /v1/auth/login` returns an access token. Send it as
`Authorization: Bearer <token>` on every other call and sign in again when it
expires. Every member may read and keep favorites; other changes need a
permission of the member's role, which `GET /v1/me` lists.

**Agents.** An agent sends a key in place of a token, the same way. A member
with `manage_members` creates keys under `/v1/agents`. A key reaches only the
operations marked `x-agent-access`: with `any` every key may call it, with
`start` only a key that may start monitoring services. `GET /v1/agents/me`
tells an agent which it is. An agent that speaks the Model Context Protocol
connects to `/v1/mcp` with its key and finds these operations as tools.

**Vocabulary.** The web app and this API name the same things differently:

- *Sources* are the `brokers`, `devices` and `readings` in the `document` of
  `GET /v1/catalogue`; `PUT /v1/recording` chooses which readings are recorded.
- Devices and readings are named by their catalogue ids: `GET /v1/devices`
  lists devices, `GET /v1/readings/{reading_id}/measurements` returns recorded
  values, and evidence and alarms take a `device_id` or `reading_id`.
- A *monitor* (`monitor_id`) watches readings; a design it can run is a
  pipeline under `/v1/pipelines`.
- An *alarm* in Reporting is under `/v1/alarms`, with its `device_id` and
  `reading_ids`.

**Changes.** Saving the catalogue takes the last `revision` as
`expected_revision`, pipeline drafts take `expected_version`; a stale value
answers 409, so read again and retry. Starting a monitor answers 202 with an
activation: poll `GET /v1/pipeline-activations/{activation_id}` until
its `phase` is `succeeded`, `failed` or `cancelled`. Errors carry a readable
`detail`.
"""

OPENAPI_TAGS = [
    {
        "name": "demo",
        "description": (
            "Discover whether this isolated installation permits public read-only "
            "browsing, and its source attribution. Never returns credentials."
        ),
    },
    {
        "name": "auth",
        "description": "Sign in, invitations and password resets. "
        "These calls need no token.",
    },
    {
        "name": "catalogue",
        "description": "Sources: the saved catalogue of brokers, devices and "
        "readings, its revisions, and broker checks.",
    },
    {
        "name": "recording",
        "description": "Which readings are recorded and how often, whether "
        "recording is healthy, and how much storage it uses.",
    },
    {
        "name": "live",
        "description": "Live views of configured readings, watched without "
        "recording them.",
    },
    {
        "name": "devices",
        "description": "Catalogue devices, whether they are sending data, and "
        "the recorded measurements of each reading.",
    },
    {
        "name": "monitors",
        "description": "Monitors: start, rename, stop and delete them, and read "
        "the pipeline each one runs with its run history.",
    },
    {
        "name": "pipelines",
        "description": "Designs (pipelines) with their drafts and revisions, the "
        "components a design may use, and activations that run a design as a "
        "monitor.",
    },
    {
        "name": "detectors",
        "description": "Detector models a monitor can use, with parameter schemas.",
    },
    {
        "name": "evidence",
        "description": "Per-observation detector scores and p-values behind alarms.",
    },
    {
        "name": "alarms",
        "description": "Alarms raised by monitors, as shown in Reporting.",
    },
    {
        "name": "favorites",
        "description": "Devices, readings and monitors the signed-in member starred.",
    },
    {
        "name": "dojo",
        "description": "The Dojo: datasets uploaded as CSV or copied from "
        "recorded readings, for comparing detection approaches offline without "
        "touching live monitoring. Needs `use_dojo`, reads included.",
    },
    {
        "name": "members",
        "description": "The signed-in member and their permissions, and with "
        "`manage_members` the organization's members and invitations.",
    },
    {
        "name": "agents",
        "description": "Agents sign in with a key in place of a password. A key "
        "reads, designs, tests and proposes; starting monitoring services is "
        "allowed per key. Members with `manage_members` create and revoke keys.",
    },
    {
        "name": "roles",
        "description": "Roles bundle permissions; every member holds one. Every "
        "member reads everything, and a permission allows changes in one area.",
    },
    {"name": "health", "description": "Liveness of the gateway itself."},
]


def operation_id(route: APIRoute) -> str:
    """Name each operation after its handler, so generated clients read well."""
    return route.name


# The gateway owns no database connection, so database settings are absent.
VALIDATION_SPECS = [
    ("app", get_app_settings),
    ("runtime", get_runtime_settings),
    ("auth", get_auth_settings),
    ("service_auth", get_service_auth_settings),
    ("email", get_email_settings),
    ("services", get_service_endpoints_settings),
    ("demo", DemoSettings),
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan manager for startup and shutdown events."""
    logger.info("Application is now running...")
    async with app.state.mcp():
        yield

    await tactic.close()
    logger.info("Application shutdown...")


async def health_check():
    """Answer while the gateway process runs; says nothing about TACTIC or data."""
    return {"status": "healthy", "service": "api-gateway"}


def build_app(
    app_settings: AppSettings, demo_settings: DemoSettings | None = None
) -> FastAPI:
    """Build the gateway from already validated settings."""
    app = FastAPI(
        title=app_settings.APP_NAME,
        description=API_DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        generate_unique_id_function=operation_id,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.include_router(api_docs_router)

    app.state.limiter = limiter
    demo_settings = demo_settings or DemoSettings()
    app.state.demo_enabled = demo_settings.DEMO_MODE
    # Only the gateway's own limiter answers with its headers; a 429 forwarded
    # from TACTIC keeps TACTIC's detail through the normal HTTPException path.
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    # Added innermost first: requests pass CORS, the correlation ID, the
    # per-client rate limit, the body size limit, GZip, SlowAPI and request
    # logging in that order. The two limits answer before routing, so they
    # also cover anonymous requests that authentication would reject later.
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SlowAPIMiddleware)
    if demo_settings.DEMO_MODE:
        app.add_middleware(DemoGuestMiddleware, settings=demo_settings)
    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(ClientRateLimitMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        # Keep defaults development-friendly via AppSettings; override in prod.
        allow_origins=list(app_settings.CORS_ALLOWED_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(v1_router, prefix="/v1")
    app.add_api_route("/health", health_check, methods=["GET"], tags=["health"])
    app.state.mcp = add_mcp(app)
    return app


def create_app() -> FastAPI:
    """Load and validate configuration, configure logging and build the app."""
    start_service(
        "api-gateway",
        Path(__file__).parent / "config" / "logging.yaml",
        VALIDATION_SPECS,
        context="API gateway configuration",
    )
    return build_app(get_app_settings())
