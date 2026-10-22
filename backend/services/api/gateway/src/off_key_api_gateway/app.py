"""Compose the API gateway application."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from off_key_core.api_docs import router as api_docs_router
from off_key_core.config.app import AppSettings, get_app_settings
from off_key_core.config.auth import get_auth_settings
from off_key_core.config.email import get_email_settings
from off_key_core.config.env import load_env
from off_key_core.config.logs import (
    CorrelationIdMiddleware,
    load_yaml_config,
    log_startup_logging_configuration,
    logger,
)
from off_key_core.config.runtime import get_runtime_settings
from off_key_core.config.service_auth import get_service_auth_settings
from off_key_core.config.services import get_service_endpoints_settings
from off_key_core.config.validation import validate_settings
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.gzip import GZipMiddleware

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


async def wait_for_db_sync(
    max_retries: int = 150,
    retry_delay: int = 2,
    acceptable_statuses: tuple[str, ...] = ("healthy", "starting"),
):
    """Wait for db-sync service to reach an acceptable readiness state.

    The API can safely start once db-sync is either fully healthy or in its
    long-running "starting" state (initial backfill still in progress).
    """
    db_sync_service_url = get_service_endpoints_settings().db_sync_service_url.rstrip(
        "/"
    )
    logger.info(f"Waiting for db-sync service at {db_sync_service_url}")

    async with httpx.AsyncClient(timeout=5.0) as client:
        for attempt in range(1, max_retries + 1):
            try:
                response = await client.get(f"{db_sync_service_url}/health")
                if response.status_code == 200:
                    data = response.json()
                    status = data.get("status")
                    if status in acceptable_statuses:
                        logger.info(
                            "db-sync service is ready "
                            f"(status={status}, acceptable={acceptable_statuses})"
                        )
                        return True
                    logger.info(
                        f"db-sync service not ready: {data.get('message', 'unknown')}"
                    )
                else:
                    logger.info(
                        f"db-sync health check returned status {response.status_code}"
                    )
            except Exception as e:
                logger.info(
                    f"Waiting for db-sync (attempt {attempt}/{max_retries}): {e}"
                )

            if attempt < max_retries:
                await asyncio.sleep(retry_delay)

        logger.warning(
            f"db-sync service did not become ready after {max_retries} attempts"
        )
        return False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan manager for startup and shutdown events."""
    await wait_for_db_sync()

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
    load_env()
    validate_settings(VALIDATION_SPECS, context="API gateway configuration")
    load_yaml_config(str(Path(__file__).parent / "config" / "logging.yaml"))
    log_startup_logging_configuration("api-gateway")
    return build_app(get_app_settings())
