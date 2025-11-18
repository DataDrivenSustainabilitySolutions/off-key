"""
TACTIC (Timely Anomaly Communication / Task Instance Control) Middleware Service

This service acts as an orchestrator between the API gateway and backend microservices,
specifically handling Docker container orchestration for RADAR services.
"""

import uvicorn

from pathlib import Path
from fastapi import FastAPI
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi.middleware.cors import CORSMiddleware
from off_key_core.config.logs import load_yaml_config, logger
from .api.v1 import radar
from .config.config import tactic_settings

# Load logging configuration from YAML files
service_logging_config = Path(__file__).parent / "config" / "logging.yaml"
load_yaml_config(str(service_logging_config))


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = tactic_settings.config

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        """FastAPI lifespan manager for startup and shutdown events."""
        logger.info("Application is now running...")

        # Validate Docker API connection
        from .facades.docker import AsyncDocker

        try:
            AsyncDocker()
        except Exception as exc:
            logger.exception(
                "Docker API connection failed; shutting down immediately",
                extra={"error": str(exc), "error_type": type(exc).__name__},
            )
            raise  # Re-raise to fail fast and stop FastAPI startup

        yield

        # Shutdown
        logger.info("Application shutdown...")

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
    config = tactic_settings.config

    logger.info(f"Starting {config.service_name} v{config.service_version}...")
    logger.info(f"Docker API: {config.docker.base_url}")
    logger.info("Service configuration loaded from environment")

    app = create_app()

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_config=None,  # Disable uvicorn's logging, use our logger
    )


if __name__ == "__main__":
    main()
