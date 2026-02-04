"""
TACTIC (Timely Anomaly Communication / Task Instance Control) Middleware Service

This service acts as an orchestrator between the API gateway and backend microservices,
specifically handling Docker container orchestration for RADAR services.
"""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from off_key_core.config.env import load_env
from off_key_core.config.logs import logger
from off_key_core.config.validation import validate_settings
from .api.v1 import radar
from .config import get_tactic_config, TacticConfig
from .services.reconciliation import RadarStatusReconciliationService
from .facades.docker import AsyncDocker


def get_validated_config() -> TacticConfig:
    """Load environment and validate required settings."""
    load_env()
    validate_settings(
        [("tactic", get_tactic_config)],
        context="TACTIC middleware configuration",
    )
    return get_tactic_config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan manager for startup and shutdown events."""
    config = get_tactic_config()

    # Validate Docker connectivity early
    docker_client = None
    try:
        docker_client = AsyncDocker()
        await docker_client.run(docker_client.client.ping)
        logger.info("Docker connectivity verified")
        app.state.docker_client = docker_client
    except Exception as exc:
        logger.exception(
            "Docker API connection failed; shutting down",
            extra={"error": str(exc), "error_type": type(exc).__name__},
        )
        if docker_client:
            try:
                docker_client.close()
            except Exception:
                pass
        raise

    # Start reconciliation service if enabled
    if config.reconciliation_enabled:
        app.state.reconciliation_service = RadarStatusReconciliationService(
            interval_seconds=config.reconciliation_interval
        )
        await app.state.reconciliation_service.start()
        interval = config.reconciliation_interval
        logger.info(f"Status reconciliation enabled (interval={interval}s)")
    else:
        app.state.reconciliation_service = None
        logger.info("Status reconciliation disabled")

    yield

    # Cleanup: stop reconciliation service
    if app.state.reconciliation_service:
        try:
            await app.state.reconciliation_service.stop()
            logger.info("Status reconciliation stopped")
        except Exception:
            logger.exception("Error stopping reconciliation service")

    # Cleanup: close Docker client
    if app.state.docker_client:
        try:
            app.state.docker_client.close()
        except Exception:
            logger.exception("Error closing Docker client")
        app.state.docker_client = None


def create_app(config: TacticConfig | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if config is None:
        config = get_validated_config()

    app = FastAPI(
        title=config.service_name,
        description="Timely Anomaly Communication / "
        "Task Instance Control for off-key platform",
        version=config.service_version,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure this properly for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routers
    app.include_router(
        radar.router, prefix="/api/v1/orchestration", tags=["orchestration"]
    )

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "service": "tactic-middleware"}

    return app


def main() -> None:
    """Main entry point for the TACTIC middleware service."""
    config = get_validated_config()

    logger.info(f"Starting {config.service_name} v{config.service_version}...")
    logger.info(f"Docker API: {config.docker.base_url}")
    logger.info("Service configuration loaded from environment")

    app = create_app(config)

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":
    main()
