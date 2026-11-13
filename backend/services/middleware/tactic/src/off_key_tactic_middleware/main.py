"""
TACTIC (Timely Anomaly Communication / Task Instance Control) worker.

The background half of the platform; the API serves every request. TACTIC
records the catalogue's sources (ingress), runs pipeline activations, and keeps
RADAR workloads and their records in step. It answers only /health and /ready.
"""

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response, status
from off_key_core.config.bootstrap import start_service
from off_key_core.config.database import get_database_settings
from off_key_core.config.logs import logger
from off_key_core.db.base import get_async_session_local

from .config.config import RadarWorkloadLifecycle, TacticConfig, get_tactic_settings
from .config.system_live import get_system_live_settings
from .facades.docker import AsyncDocker
from .services.catalogue.broker_access import BrokerRouteAccess
from .services.catalogue.system_ingress import SystemIngress
from .services.orchestration.radar import RadarOrchestrationService
from .services.orchestration.radar_workloads import (
    RadarWorkloadManager,
    set_shared_async_docker,
)
from .services.orchestration.reconciliation import RadarStatusReconciliationService
from .services.pipelines.supervisor import PipelineActivationSupervisor


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
    # Activations, collection pauses and teardown share this client and its
    # concurrency cap; the reconciliation sweep keeps its own (see below).
    set_shared_async_docker(docker_client)
    logger.info("Docker connectivity verified")


async def _start_reconciliation(app: FastAPI, config: TacticConfig) -> None:
    """Start background status reconciliation when configured."""
    if not config.reconciliation_enabled:
        logger.info("Status reconciliation disabled")
        return

    # A separate client keeps the periodic sweep from starving activations.
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


async def _shutdown_services(app: FastAPI, config: TacticConfig) -> None:
    """Best-effort shutdown for every service initialized during startup."""
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
    app.state.pipeline_activation_supervisor = None
    app.state.system_ingress = None

    try:
        await _connect_docker(app)

        if config.radar_workload_lifecycle == RadarWorkloadLifecycle.EPHEMERAL:
            await _teardown_ephemeral_radar_workloads(app, phase="startup")
        else:
            logger.info(
                "RADAR workload lifecycle is persistent; startup cleanup skipped"
            )

        await _start_reconciliation(app, config)
        app.state.pipeline_activation_supervisor = PipelineActivationSupervisor(
            RadarWorkloadManager(app.state.docker_client)
        )
        await app.state.pipeline_activation_supervisor.start()
        app.state.system_ingress = SystemIngress(
            access_resolver=BrokerRouteAccess(get_system_live_settings()),
        )
        await app.state.system_ingress.start()
        yield
    finally:
        await _shutdown_services(app, config)


def create_app() -> FastAPI:
    """The worker's process: background services plus its own probes."""
    config = get_tactic_settings().config

    app = FastAPI(
        title=config.service_name,
        version=config.service_version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "service": "tactic-middleware"}

    @app.get("/ready")
    async def readiness_check(request: Request, response: Response):
        """Readiness endpoint that requires docker connectivity."""
        # Before the lifespan runs (bare test apps) there is no client yet.
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
    """Main entry point for the TACTIC worker."""
    start_service(
        "tactic",
        Path(__file__).parent / "config" / "logging.yaml",
        [
            ("tactic", lambda: get_tactic_settings().config),
            ("database", get_database_settings),
            ("system_live", get_system_live_settings),
        ],
        context="TACTIC worker configuration",
    )
    config = get_tactic_settings().config

    logger.info(f"Starting {config.service_name} v{config.service_version}...")
    logger.info(f"Docker API: {config.docker.base_url}")

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
