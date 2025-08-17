from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from off_key_core.config import settings
from off_key_core.db import AsyncSessionLocal

from .api.middleware import add_process_time_header
from .api.v1.routes import api_router
from .dependencies import get_background_sync_service
from .services.background_sync import BackgroundSyncService
from .services.chargers import ChargersSyncService
from .services.telemetry import TelemetrySyncService


# Rate limiter setup
def get_real_client_ip(request):
    return request.client.host


limiter = Limiter(key_func=get_real_client_ip)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan manager for startup and shutdown events."""
    
    # Startup
    if settings.SYNC_ENABLED:
        # Create dependency factories for services
        def charger_sync_factory(session):
            from .dependencies import get_charger_api_client
            client = get_charger_api_client()
            return ChargersSyncService(session, client)

        def telemetry_sync_factory(session):
            from .dependencies import get_charger_api_client
            client = get_charger_api_client()
            return TelemetrySyncService(session, client)

        # Initialize and start background sync service
        background_sync = BackgroundSyncService(
            charger_sync_factory, telemetry_sync_factory
        )
        
        app.state.background_sync = background_sync
        await background_sync.start()

    yield

    # Shutdown
    if hasattr(app.state, "background_sync"):
        await app.state.background_sync.stop()


# FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    description="Off-Key API Gateway - Real-time Anomaly Detection Platform",
    lifespan=lifespan,
)

# Middleware
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(add_process_time_header)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(api_router, prefix="/v1")


@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint that verifies the app and its dependencies are running.
    Returns status of various components without exposing sensitive information.
    """
    # TODO What is considered "healthy" now?
    ...

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True if settings.DEBUG else False
    )
