"""
TACTIC (Timely Anomaly Communication / Task Instance Control) Middleware Service

This service acts as an orchestrator between the API gateway and backend microservices,
specifically handling Docker container orchestration for RADAR services.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

from off_key_core.config.env import load_env
from off_key_core.config.validation import validate_settings
from off_key_core.config.logs import (
    logger,
    load_yaml_config,
    log_startup_logging_configuration,
)
from off_key_core.db.base import get_async_session_local
from .api.v1 import radar, models, data_services
from .api.v1.admin_models import router as admin_models_router
from .config.config import get_tactic_settings, RadarWorkloadLifecycle
from .services.reconciliation import RadarStatusReconciliationService
from .facades.docker import AsyncDocker
from .models.registry import ModelRegistryService, ModelRegistryNotReadyError
from .services.orchestration.radar import RadarOrchestrationService


async def _initialize_model_registry(
    app: FastAPI,
    *,
    max_retries: int,
    retry_interval_seconds: float,
    log_as_exception: bool,
) -> bool:
    """Initialize model registry once and update app state."""
    model_registry = getattr(app.state, "model_registry", None)
    if model_registry is None:
        model_registry = ModelRegistryService()
        app.state.model_registry = model_registry

    try:
        await model_registry.initialize(
            max_retries=max_retries,
            retry_interval_seconds=retry_interval_seconds,
        )
        app.state.model_registry_ready = True
        logger.info("Model registry ready")
        return True
    except ModelRegistryNotReadyError as exc:
        app.state.model_registry_ready = False
        if log_as_exception:
            logger.exception(
                "Model registry initialization failed; model endpoints will return "
                "503 until recovery succeeds",
                extra={"error": str(exc), "error_type": type(exc).__name__},
            )
        else:
            logger.warning(
                "Model registry still not ready; retrying in %.1fs (%s)",
                retry_interval_seconds,
                exc,
            )
        return False


async def _model_registry_recovery_loop(app: FastAPI) -> None:
    """Retry model registry initialization in background until ready."""
    config = get_tactic_settings().config
    retry_interval = config.model_registry_init_retry_interval_seconds

    logger.info(
        "Starting model registry recovery loop (retry_interval=%.1fs)",
        retry_interval,
    )

    while True:
        ready = await _initialize_model_registry(
            app,
            max_retries=1,
            retry_interval_seconds=retry_interval,
            log_as_exception=False,
        )
        if ready:
            logger.info("Model registry recovery completed")
            return
        await asyncio.sleep(retry_interval)


async def _teardown_ephemeral_radar_workloads(app: FastAPI, phase: str) -> None:
    """Destroy all managed RADAR workloads and clear DB service records."""
    session_factory = get_async_session_local()
    async with session_factory() as session:
        service = RadarOrchestrationService(
            session=session,
            model_registry=app.state.model_registry,
        )
        summary = await service.teardown_managed_radar_workloads()

    logger.info(
        "Ephemeral RADAR cleanup complete (%s): targeted=%d removed=%d db_rows=%d",
        phase,
        summary["workloads_targeted"],
        summary["docker_workloads_removed"],
        summary["db_rows_deleted"],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan manager for startup and shutdown events."""
    config = get_tactic_settings().config

    app.state.model_registry = ModelRegistryService()
    app.state.model_registry_ready = False
    app.state.model_registry_recovery_task = None

    # Initialize model registry with bounded startup retries.
    model_registry_ready = await _initialize_model_registry(
        app,
        max_retries=config.model_registry_init_max_retries,
        retry_interval_seconds=config.model_registry_init_retry_interval_seconds,
        log_as_exception=True,
    )
    if not model_registry_ready:
        app.state.model_registry_recovery_task = asyncio.create_task(
            _model_registry_recovery_loop(app),
            name="tactic-model-registry-recovery",
        )

    # Validate Docker connectivity early
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
        raise

    if config.radar_workload_lifecycle == RadarWorkloadLifecycle.EPHEMERAL:
        await _teardown_ephemeral_radar_workloads(app, phase="startup")
    else:
        logger.info("RADAR workload lifecycle is persistent; startup cleanup skipped")

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

    if config.radar_workload_lifecycle == RadarWorkloadLifecycle.EPHEMERAL:
        try:
            await _teardown_ephemeral_radar_workloads(app, phase="shutdown")
        except Exception:
            logger.exception("Failed to teardown ephemeral RADAR workloads")

    # Cleanup: close Docker client
    if app.state.docker_client:
        try:
            app.state.docker_client.close()
        except Exception:
            logger.exception("Error closing Docker client")
        app.state.docker_client = None

    recovery_task = getattr(app.state, "model_registry_recovery_task", None)
    if recovery_task:
        recovery_task.cancel()
        try:
            await recovery_task
        except asyncio.CancelledError:
            pass
        app.state.model_registry_recovery_task = None

    app.state.model_registry_ready = False
    app.state.model_registry = None


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = get_tactic_settings().config

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
    app.include_router(
        data_services.router, prefix="/api/v1/data", tags=["data-services"]
    )
    app.include_router(models.router, prefix="/api/v1", tags=["models"])
    app.include_router(admin_models_router, prefix="/api/v1", tags=["admin"])

    @app.get("/health")
    async def health_check(request: Request):
        """Health check endpoint."""
        return {
            "status": "healthy",
            "service": "tactic-middleware",
            "model_registry_ready": getattr(
                request.app.state,
                "model_registry_ready",
                False,
            ),
        }

    @app.get("/ready")
    async def readiness_check(request: Request, response: Response):
        """Readiness endpoint that requires model registry and docker connectivity."""
        model_registry_ready = getattr(request.app.state, "model_registry_ready", False)
        docker_ready = getattr(request.app.state, "docker_client", None) is not None
        ready = model_registry_ready and docker_ready
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        return {
            "status": "ready" if ready else "not_ready",
            "service": "tactic-middleware",
            "model_registry_ready": model_registry_ready,
            "docker_ready": docker_ready,
        }

    return app


def main() -> None:
    """Main entry point for the TACTIC middleware service."""
    load_env()
    service_logging_config = Path(__file__).parent / "config" / "logging.yaml"
    load_yaml_config(str(service_logging_config))
    log_startup_logging_configuration("tactic")

    validate_settings(
        [("tactic", lambda: get_tactic_settings().config)],
        context="TACTIC middleware configuration",
    )
    config = get_tactic_settings().config

    logger.info(f"Starting {config.service_name} v{config.service_version}...")
    logger.info(f"Docker API: {config.docker.base_url}")
    logger.info("Service configuration loaded from environment")

    app = create_app()

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":
    main()
