from datetime import datetime

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .db.base import async_engine, get_db_async
from .core.config import settings
from .core.logs import setup_logging, LogFormat
from .api.rate_limiter import limiter, rate_limit_exceeded_handler
from .api.v1.routes import router as v1_router
from .api.middleware import LoggingMiddleware, SecurityLoggingMiddleware
from .db.models import Base
from .services.background_sync import BackgroundSyncService
from .core.dependencies import get_charger_api_client, get_background_sync_service

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

app = FastAPI(title=settings.APP_NAME)

app.state.limiter = limiter
app.add_exception_handler(429, rate_limit_exceeded_handler)

# Background sync service will be initialized in startup_event with dependency injection

origins = ["http://localhost:8000", "http://localhost:5173"]

# Add custom logging middleware first (innermost)
app.add_middleware(LoggingMiddleware)
app.add_middleware(SecurityLoggingMiddleware)

# Enable SlowApi Middleware
app.add_middleware(SlowAPIMiddleware)

# Enable CORS Middleware (outermost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow only specified origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods (POST, GET, etc.)
    allow_headers=["*"],  # Allow all headers
)


# Create database tables and start background services on startup
@app.on_event("startup")
async def startup_event():
    """Create database tables and start background services on application startup"""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created successfully")

    # Composition Root - Resolve dependencies ONCE
    api_client = get_charger_api_client()
    logger.info(f"Initialized API client: {type(api_client).__name__}")

    # Inject dependencies into services
    background_sync = BackgroundSyncService(api_client)
    app.state.background_sync = background_sync  # Store for shutdown

    # Start background sync service
    await background_sync.start()
    logger.info("Background sync service started")


# Stop background services on shutdown
@app.on_event("shutdown")
async def shutdown_event():
    """Stop background services on application shutdown"""
    if hasattr(app.state, "background_sync"):
        await app.state.background_sync.stop()
        logger.info("Background sync service stopped")


# Include versioned API routes
app.include_router(v1_router, prefix="/v1", tags=["v1"])


@app.get("/health")
async def health_check(
    db: AsyncSession = Depends(get_db_async),
    sync_service: BackgroundSyncService = Depends(get_background_sync_service),
):
    """
    Health check endpoint that verifies the app and its dependencies are running.
    Returns status of various components without exposing sensitive information.
    """
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": settings.APP_NAME,
        "checks": {
            "api": "healthy",
            "database": "unhealthy",
            "background_sync": "healthy",
        },
    }

    # Check database connectivity
    try:
        # Simple query to verify database connection
        await db.execute(text("SELECT 1"))
        health_status["checks"]["database"] = "healthy"
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["checks"]["database"] = "unhealthy"
        logger.error(f"Database health check failed: {str(e)}")

    # Check background sync service (clean, explicit dependency)
    try:
        sync_status = sync_service.get_status()
        if sync_status["enabled"] and not sync_status["running"]:
            health_status["checks"]["background_sync"] = "unhealthy"
            health_status["status"] = "unhealthy"
        elif not sync_status["enabled"]:
            health_status["checks"]["background_sync"] = "disabled"
    except Exception as e:
        health_status["checks"]["background_sync"] = "unhealthy"
        health_status["status"] = "unhealthy"
        logger.error(f"Background sync health check failed: {str(e)}")

    # Return appropriate status code based on overall health
    status_code = 200 if health_status["status"] == "healthy" else 503
    return JSONResponse(content=health_status, status_code=status_code)


@app.get("/health/live")
async def liveness_check():
    """
    Liveness probe endpoint for Kubernetes/Docker health checks.
    Simple check that the application is running.
    """
    return JSONResponse(
        content={
            "status": "alive",
            "timestamp": datetime.utcnow().isoformat(),
            "service": settings.APP_NAME,
        },
        status_code=200,
    )
