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
    get_app_settings,
    get_service_endpoints_settings,
)

from .api.middleware import RequestLoggingMiddleware
from .api.rate_limiter import limiter, rate_limit_exceeded_handler
from .api.v1.routes import router as v1_router
from .facades.tactic import tactic

API_DESCRIPTION = """\
The gateway API of one Aberration installation: its MQTT sources, the readings
it records, the monitors that watch them and the alarms they raise. The web app
uses this same API, so every change it makes can be made here.

**Base URL.** Behind the dashboard the API lives under `/api`, which the
`servers` entry of this document states: `/v1/anomalies` is called as
`https://<dashboard>/api/v1/anomalies`.

**Authentication.** `POST /v1/auth/login` returns an access token. Send it as
`Authorization: Bearer <token>` on every other call and sign in again when it
expires. Every member may read and keep favorites; other changes need a
permission of the member's role, which `GET /v1/me` lists.

**Vocabulary.** The web app and this API name the same things differently:

- *Sources* are the brokers (`connections`), `devices` and readings
  (`streams`) in the `document` of `GET /v1/system`.
- A *reading* is recorded under `charger_id` (its entity) plus `telemetry_type`
  (its key), which telemetry, evidence and alarms use. `GET /v1/system` maps
  each stream id to that pair as `entity_id` and `telemetry_key` in
  `runtime.bindings`.
- A *monitor* is a monitoring service (`service_id`); its design is a pipeline
  under `/v1/monitors/pipelines`.
- An *alarm* in Reporting is an anomaly under `/v1/anomalies`.

**Changes.** Saving the catalogue takes the last `revision` as
`expected_revision`, pipeline drafts take `expected_version`; a stale value
answers 409, so read again and retry. Starting a monitor answers 202 with an
activation: poll `GET /v1/monitors/pipeline-activations/{activation_id}` until
its `phase` is `succeeded`, `failed` or `cancelled`. Errors carry a readable
`detail`.
"""

OPENAPI_TAGS = [
    {
        "name": "auth",
        "description": "Sign in, invitations and password resets. "
        "These calls need no token.",
    },
    {
        "name": "system",
        "description": "Sources: the saved catalogue of brokers, devices and "
        "readings, what is recorded, collection health and live preview.",
    },
    {
        "name": "chargers",
        "description": "Recorded entities, the `charger_id` that telemetry, "
        "evidence and alarms are keyed by.",
    },
    {
        "name": "telemetry",
        "description": "Recorded values of one entity, by telemetry type.",
    },
    {
        "name": "monitors",
        "description": "Monitors, their designs (pipelines), activations, runs "
        "and detector evidence.",
    },
    {
        "name": "anomalies",
        "description": "Alarms raised by monitors, as shown in Reporting.",
    },
    {
        "name": "favorites",
        "description": "Entities, readings and monitors the signed-in member starred.",
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
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan manager for startup and shutdown events."""
    logger.info("Application is now running...")
    yield

    await tactic.close()
    logger.info("Application shutdown...")


async def health_check():
    """Answer while the gateway process runs; says nothing about TACTIC or data."""
    return {"status": "healthy", "service": "api-gateway"}


def build_app(app_settings: AppSettings) -> FastAPI:
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
    # Only the gateway's own limiter answers with its headers; a 429 forwarded
    # from TACTIC keeps TACTIC's detail through the normal HTTPException path.
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    # Added innermost first: requests pass CORS, the correlation ID, GZip,
    # SlowAPI and request logging in that order.
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)
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
