"""Compose the API gateway application."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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

from .api.middleware import LoggingMiddleware, SecurityLoggingMiddleware
from .api.rate_limiter import limiter, rate_limit_exceeded_handler
from .api.v1.routes import router as v1_router
from .facades.tactic import tactic

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
    """
    Return basic API gateway liveness.
    """
    return {"status": "healthy", "service": "api-gateway"}


def build_app(app_settings: AppSettings) -> FastAPI:
    """Build the gateway from already validated settings."""
    app = FastAPI(
        title=app_settings.APP_NAME,
        description="aberration API Gateway - Real-time Anomaly Detection Platform",
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
    # SlowAPI, security logging and request logging in that order.
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(SecurityLoggingMiddleware)
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

    app.include_router(v1_router, prefix="/v1", tags=["v1"])
    app.add_api_route("/health", health_check, methods=["GET"], tags=["Health"])
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
