from contextlib import asynccontextmanager
from typing import AsyncGenerator
import asyncio
import httpx
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware

from off_key_core.config.app import get_app_settings
from off_key_core.config.auth import get_auth_settings
from off_key_core.config.email import get_email_settings
from off_key_core.config.env import load_env
from off_key_core.config.runtime import get_runtime_settings
from off_key_core.config.services import get_service_endpoints_settings
from off_key_core.config.validation import validate_settings
from off_key_core.config.logs import load_yaml_config, logger

from .api.middleware import LoggingMiddleware, SecurityLoggingMiddleware
from .api.rate_limiter import limiter, rate_limit_exceeded_handler
from .api.v1.routes import router as v1_router
from .facades.tactic import tactic

load_env()
validate_settings(
    [
        ("app", get_app_settings),
        ("runtime", get_runtime_settings),
        ("auth", get_auth_settings),
        ("email", get_email_settings),
        ("services", get_service_endpoints_settings),
    ],
    context="API gateway configuration",
)

app_settings = get_app_settings()
runtime_settings = get_runtime_settings()
service_endpoints = get_service_endpoints_settings()

# Rate limiter setup
# def get_real_client_ip(request):
#     return request.client.host
#
#
# limiter = Limiter(key_func=get_real_client_ip)


# See https://github.com/pyca/bcrypt/issues/684#issuecomment-2465572106
import bcrypt  # noqa: E402

if not hasattr(bcrypt, "__about__"):
    bcrypt.__about__ = type("about", (object,), {"__version__": bcrypt.__version__})

# Initialize logging from core + service YAML config
service_logging_config = Path(__file__).parent / "config" / "logging.yaml"
load_yaml_config(str(service_logging_config))


async def wait_for_db_sync(
    max_retries: int = 150,
    retry_delay: int = 2,
    acceptable_statuses: tuple[str, ...] = ("healthy", "starting"),
):
    """Wait for db-sync service to reach an acceptable readiness state.

    The API can safely start once db-sync is either fully healthy or in its
    long-running "starting" state (initial backfill still in progress).
    """
    db_sync_service_url = service_endpoints.db_sync_service_url.rstrip("/")
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
                    else:
                        logger.info(
                            f"db-sync service not ready: "
                            f"{data.get('message', 'unknown')}"
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
    # Wait for db-sync service to be ready
    await wait_for_db_sync()

    logger.info("Application is now running...")
    yield

    # Shutdown
    await tactic.close()
    logger.info("Application shutdown...")


# FastAPI app
app = FastAPI(
    title=app_settings.APP_NAME,
    description="Off-Key API Gateway - Real-time Anomaly Detection Platform",
    lifespan=lifespan,
)

# Middleware
app.state.limiter = limiter
app.add_exception_handler(429, rate_limit_exceeded_handler)

# Add custom logging middleware first (innermost)
app.add_middleware(LoggingMiddleware)
app.add_middleware(SecurityLoggingMiddleware)

# Enable SlowApi Middleware
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    # Keep defaults development-friendly via AppSettings, and override via env in prod.
    allow_origins=list(app_settings.CORS_ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(v1_router, prefix="/v1", tags=["v1"])


# TODO: Rethink healthcheck as a (micro)service. TODO What is considered "healthy" now?
@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint that verifies the app and its dependencies are running.
    Returns status of various components without exposing sensitive information.
    """
    ...


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=runtime_settings.DEBUG,
    )
