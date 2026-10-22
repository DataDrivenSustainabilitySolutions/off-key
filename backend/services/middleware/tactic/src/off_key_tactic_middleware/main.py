"""
TACTIC (Timely Anomaly Communication / Task Instance Control) Middleware Service

This service acts as an orchestrator between the API gateway and backend microservices,
specifically handling Docker container orchestration for RADAR services.
"""

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from off_key_core.api_docs import router as api_docs_router
from off_key_core.config.auth import get_auth_settings
from off_key_core.config.env import load_env
from off_key_core.config.logs import (
    load_yaml_config,
    log_startup_logging_configuration,
    logger,
)
from off_key_core.config.service_auth import get_service_auth_settings
from off_key_core.config.validation import validate_settings
from off_key_core.db.base import get_async_session_local
from off_key_core.db.maintenance import DeploymentInProgressError
from starlette.middleware.gzip import GZipMiddleware

from .api.service_auth import require_gateway
from .api.v1 import data_services, members, models, pipelines, radar, system
from .config.collection import get_ambibox_settings
from .config.config import RadarWorkloadLifecycle, TacticConfig, get_tactic_settings
from .config.system_live import get_system_live_settings
from .facades.docker import AsyncDocker
from .services.ambibox_live_access import AmbiboxLiveAccess
from .services.orchestration.radar import RadarOrchestrationService
from .services.orchestration.radar_workloads import (
    RadarWorkloadManager,
    set_shared_async_docker,
)
from .services.reconciliation import RadarStatusReconciliationService
from .services.system import SystemService
from .services.system_live import SystemLiveService


async def _teardown_ephemeral_radar_workloads(app: FastAPI, phase: str) -> None:
    """Destroy all managed RADAR workloads and clear DB service records."""
    session_factory = get_async_session_local()
    async with session_factory() as session:
        service = RadarOrchestrationService(session)
        summary = await service.teardown_managed_radar_workloads()

    logger.info(
        "Ephemeral RADAR cleanup complete (%s): targeted=%d removed=%d db_rows=%d",
        phase,
        summary["workloads_targeted"],
        summary["docker_workloads_removed"],
        summary["db_rows_deleted"],
    )


async def _connect_docker(app: FastAPI) -> None:
    """Connect to Docker and retain only a verified client."""
    docker_client = AsyncDocker()
    try:
        await docker_client.run(docker_client.client.ping)
    except Exception as exc:
        docker_client.close()
        logger.exception(
            "Docker API connection failed; shutting down",
            extra={"error": str(exc), "error_type": type(exc).__name__},
        )
        raise

    app.state.docker_client = docker_client
    # Request paths, collection pauses and teardown share this client and its
    # concurrency cap; the reconciliation sweep keeps its own (see below).
    set_shared_async_docker(docker_client)
    logger.info("Docker connectivity verified")


async def _start_reconciliation(app: FastAPI, config: TacticConfig) -> None:
    """Start background status reconciliation when configured."""
    if not config.reconciliation_enabled:
        logger.info("Status reconciliation disabled")
        return

    # A separate client keeps the periodic sweep from starving request paths.
    reconciliation_service = RadarStatusReconciliationService(
        interval_seconds=config.reconciliation_interval,
        terminal_service_retention_hours=config.terminal_service_retention_hours,
    )
    app.state.reconciliation_service = reconciliation_service
    await reconciliation_service.start()
    logger.info(
        "Status reconciliation enabled (interval=%ss)",
        config.reconciliation_interval,
    )


async def _shutdown_system_live(app: FastAPI) -> None:
    live = getattr(app.state, "system_live", None)
    if live is not None:
        try:
            await live.close()
        except Exception:
            logger.exception("Error stopping generic live observation")
        finally:
            app.state.system_live = None


async def _shutdown_services(app: FastAPI, config: TacticConfig) -> None:
    """Best-effort shutdown for every service initialized during startup."""
    await _shutdown_system_live(app)
    for attribute in (
        "pipeline_activation_supervisor",
        "system_ingress",
        "reconciliation_service",
    ):
        service = getattr(app.state, attribute, None)
        if service is not None:
            try:
                await service.stop()
            except Exception:
                logger.exception("Error stopping %s", attribute)
            setattr(app.state, attribute, None)

    if (
        config.radar_workload_lifecycle == RadarWorkloadLifecycle.EPHEMERAL
        and app.state.docker_client is not None
    ):
        try:
            await _teardown_ephemeral_radar_workloads(app, phase="shutdown")
        except Exception:
            logger.exception("Failed to teardown ephemeral RADAR workloads")

    docker_client = app.state.docker_client
    if docker_client is not None:
        try:
            docker_client.close()
        except Exception:
            logger.exception("Error closing Docker client")
        finally:
            app.state.docker_client = None
            set_shared_async_docker(None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan manager for startup and shutdown events."""
    config = get_tactic_settings().config

    app.state.docker_client = None
    app.state.reconciliation_service = None
    app.state.system_live = None

    try:
        await _connect_docker(app)

        if config.radar_workload_lifecycle == RadarWorkloadLifecycle.EPHEMERAL:
            await _teardown_ephemeral_radar_workloads(app, phase="startup")
        else:
            logger.info(
                "RADAR workload lifecycle is persistent; startup cleanup skipped"
            )

        await _start_reconciliation(app, config)
        from .services.pipelines.supervisor import PipelineActivationSupervisor

        app.state.pipeline_activation_supervisor = PipelineActivationSupervisor(
            RadarWorkloadManager(app.state.docker_client)
        )
        await app.state.pipeline_activation_supervisor.start()
        operator_access = AmbiboxLiveAccess(get_ambibox_settings())
        app.state.system_live = SystemLiveService(
            get_system_live_settings(),
            access_resolver=operator_access,
        )
        from .services.system_ingress import SystemIngress

        app.state.system_ingress = SystemIngress(
            access_resolver=operator_access,
        )
        await app.state.system_ingress.start()

        async def read_live_configuration():
            async with get_async_session_local()() as session:
                return await SystemService(session).read()

        app.state.system_live.start_supervisor(read_live_configuration)
        yield
    finally:
        await _shutdown_services(app, config)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    config = get_tactic_settings().config

    app = FastAPI(
        title=config.service_name,
        description="Timely Anomaly Communication / "
        "Task Instance Control for aberration",
        version=config.service_version,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.include_router(api_docs_router)

    @app.exception_handler(DeploymentInProgressError)
    async def deployment_in_progress(request: Request, exc: DeploymentInProgressError):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure this properly for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)

    business = APIRouter(dependencies=[Depends(require_gateway)])
    business.include_router(
        radar.router, prefix="/api/v1/orchestration", tags=["orchestration"]
    )
    business.include_router(
        data_services.router, prefix="/api/v1/data", tags=["data-services"]
    )
    business.include_router(models.router, prefix="/api/v1", tags=["models"])
    business.include_router(pipelines.router, prefix="/api/v1", tags=["pipelines"])
    business.include_router(system.router, prefix="/api/v1")

    business.include_router(members.router, prefix="/api/v1")
    app.include_router(business)

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "service": "tactic-middleware"}

    @app.get("/ready")
    async def readiness_check(request: Request, response: Response):
        """Readiness endpoint that requires docker connectivity."""
        ready = getattr(request.app.state, "docker_client", None) is not None
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        return {
            "status": "ready" if ready else "not_ready",
            "service": "tactic-middleware",
            "docker_ready": ready,
        }

    return app


def main() -> None:
    """Main entry point for the TACTIC middleware service."""
    load_env()
    service_logging_config = Path(__file__).parent / "config" / "logging.yaml"
    load_yaml_config(str(service_logging_config))
    log_startup_logging_configuration("tactic")

    validate_settings(
        [
            ("tactic", lambda: get_tactic_settings().config),
            ("auth", get_auth_settings),
            ("service_auth", get_service_auth_settings),
        ],
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
        log_config=None,  # Keep the service YAML handlers and formatters
    )


if __name__ == "__main__":
    main()
