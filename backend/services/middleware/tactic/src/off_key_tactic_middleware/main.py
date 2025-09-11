"""
TACTIC (Timely Anomaly Communication / Task Instance Control) Middleware Service

This service acts as an orchestrator between the API gateway and backend microservices,
specifically handling Docker container orchestration for RADAR services.
"""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from off_key_core.config.logs import logger
from .api.v1 import radar
from .config import tactic_settings


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = tactic_settings.config
    
    app = FastAPI(
        title=config.service_name,
        description="Timely Anomaly Communication / Task Instance Control for off-key platform",
        version=config.service_version,
        docs_url="/docs",
        redoc_url="/redoc",
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
    app.include_router(radar.router, prefix="/api/v1/orchestration", tags=["orchestration"])

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
    logger.info(f"Service configuration loaded from environment")
    
    app = create_app()
    
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":
    main()