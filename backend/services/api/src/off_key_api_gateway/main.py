# TODO: Check start logic as a (micro)service
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware

from off_key_core.config.config import settings
from off_key_core.config.logs import setup_logging, LogFormat
from off_key_core.db.base import async_engine
from off_key_core.db.models import Base

from .api.middleware import LoggingMiddleware, SecurityLoggingMiddleware
from .api.rate_limiter import limiter, rate_limit_exceeded_handler
from .api.v1.routes import router as v1_router
from .services.background_sync import BackgroundSyncService
from .services.chargers import ChargersSyncService
from .services.telemetry import TelemetrySyncService

# Rate limiter setup
# def get_real_client_ip(request):
#     return request.client.host
#
#
# limiter = Limiter(key_func=get_real_client_ip)


# See https://github.com/pyca/bcrypt/issues/684#issuecomment-2465572106
import bcrypt

if not hasattr(bcrypt, "__about__"):
    bcrypt.__about__ = type("about", (object,), {"__version__": bcrypt.__version__})

# Initialize logging with configuration
log_format = (
    LogFormat.JSON if settings.LOG_FORMAT.lower() == "json" else LogFormat.SIMPLE
)
logger = setup_logging(
    app_name=settings.APP_NAME,
    log_level=settings.LOG_LEVEL,
    log_format=log_format,
    enable_correlation=True,
)


# Helper functions for startup tasks
async def _initialize_database():
    """Creates all database tables."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created successfully")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan manager for startup and shutdown events."""
    # Initialize database
    await _initialize_database()

    # Startup
    if settings.SYNC_ENABLED:
        # Create dependency factories for services
        def charger_sync_factory(session):
            from .provider import get_charger_api_client

            client = get_charger_api_client()
            return ChargersSyncService(session, client)

        def telemetry_sync_factory(session):
            from .provider import get_charger_api_client

            client = get_charger_api_client()
            return TelemetrySyncService(session, client)

        # Initialize and start background sync service
        background_sync = BackgroundSyncService(
            charger_sync_factory, telemetry_sync_factory
        )

        app.state.background_sync = background_sync
        await background_sync.start()

    # Application is now running
    yield

    # Shutdown
    logger.info("Application shutdown...")
    if hasattr(app.state, "background_sync"):
        await app.state.background_sync.stop()
    logger.info("Background sync service stopped")


# FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
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
    allow_origins=["*"],
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
        "main:app", host="0.0.0.0", port=8000, reload=True if settings.DEBUG else False
    )
