from datetime import datetime

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .db.base import async_engine, get_db_async
from .core.config import settings
from .core.logs import logger
from .api.rate_limiter import limiter, rate_limit_exceeded_handler
from .api.v1.routes import router as v1_router
from .db.models import Base

# See https://github.com/pyca/bcrypt/issues/684#issuecomment-2465572106
import bcrypt

if not hasattr(bcrypt, "__about__"):
    bcrypt.__about__ = type("about", (object,), {"__version__": bcrypt.__version__})

app = FastAPI(title=settings.APP_NAME)

app.state.limiter = limiter
app.add_exception_handler(429, rate_limit_exceeded_handler)

origins = ["http://localhost:8000", "http://localhost:5173"]

# Enable SlowApi Middleware
app.add_middleware(SlowAPIMiddleware)

# Enable CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow only specified origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods (POST, GET, etc.)
    allow_headers=["*"],  # Allow all headers
)


# Create database tables on startup
@app.on_event("startup")
async def startup_event():
    """Create database tables on application startup"""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created successfully")


# Include versioned API routes
app.include_router(v1_router, prefix="/v1", tags=["v1"])


@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db_async)):
    """
    Health check endpoint that verifies the app and its dependencies are running.
    Returns status of various components without exposing sensitive information.
    """
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": settings.APP_NAME,
        "checks": {"api": "healthy", "database": "unhealthy"},
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
