"""Private CLI for resumable release maintenance; run through trusted SSH only."""

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime

import docker
from off_key_core.db.base import get_async_session_local
from off_key_core.db.collection import lock_collection_configuration
from off_key_core.db.models import DeploymentMaintenance, MonitoringService, PipelineRun
from off_key_core.db.pipeline_claims import (
    monitor_claim_condition,
    require_no_pipeline_activation,
)
from off_key_core.schemas.radar import RadarStartConfig
from sqlalchemy import select, text

from .models.registry import ModelRegistryService
from .services.orchestration.radar import RadarOrchestrationService
from .services.orchestration.radar_workloads import (
    RadarWorkloadManager,
    get_async_docker,
)
from .services.pipelines.release import (
    normalize_saved_launch,
    prepare_release_monitors,
    record_release_run,
)

TERMINAL_TASKS = {"shutdown", "complete", "failed", "rejected", "remove"}


def captured_configuration(name: str, environment: list[str]) -> dict:
    """One-time capture of pre-integration workers, excluding runtime credentials."""
    values = dict(value.split("=", 1) for value in environment if "=" in value)
    config = normalize_saved_launch(
        {
            "container_name": name,
            "mqtt_topics": values["RADAR_SUBSCRIPTION_TOPICS"].split(","),
            "monitoring": json.loads(values["RADAR_MONITORING_CONFIG"]),
            "performance_config": {
                "sensor_key_strategy": values["RADAR_SENSOR_KEY_STRATEGY"],
                "sensor_freshness_seconds": float(
                    values["RADAR_SENSOR_FRESHNESS_SECONDS"]
                ),
            },
            "mqtt_config": {
                "qos": int(values["RADAR_SUBSCRIPTION_QOS"]),
                "client_id_prefix": values["RADAR_MQTT_CLIENT_ID_PREFIX"],
            },
        }
    )
    return config.model_dump(mode="json")


async def capture_existing(session, workloads: RadarWorkloadManager) -> dict:
    await lock_collection_configuration(session)
    operation = await session.get(DeploymentMaintenance, 1)
    if operation is not None and operation.phase not in {"complete", "quiescing"}:
        raise ValueError("Finish the pending deployment before capturing configuration")
    services = await session.scalars(
        select(MonitoringService).where(monitor_claim_condition())
    )
    count = 0
    for service in services:
        configuration = service.launch_config or {}
        if all(
            key in configuration
            for key in ("container_name", "mqtt_topics", "monitoring")
        ):
            continue
        workload = await workloads.async_docker.run(
            workloads.async_docker.client.services.get, service.container_id
        )
        environment = workload.attrs["Spec"]["TaskTemplate"]["ContainerSpec"]["Env"]
        service.launch_config = captured_configuration(
            service.container_name, environment
        )
        if configuration.get("display_name"):
            service.launch_config["display_name"] = configuration["display_name"]
        count += 1
    await session.commit()
    return {"captured": count}


async def prepare_operation(session, workloads, revision: str):
    await lock_collection_configuration(session)
    await require_no_pipeline_activation(session)
    operation = await session.get(DeploymentMaintenance, 1)
    if operation is not None and operation.phase != "complete":
        if operation.revision != revision:
            raise ValueError("A different release requires recovery before deploying")
        if operation.phase != "quiescing":
            await session.commit()
            return operation
    snapshots = []
    services = await session.scalars(
        select(MonitoringService).where(monitor_claim_condition())
    )
    for service in services:
        restart = service.stop_requested_at is None
        if restart and not all(
            key in (service.launch_config or {})
            for key in ("container_name", "mqtt_topics", "monitoring")
        ):
            raise ValueError(
                "Capture existing active monitor configuration before cutover"
            )
        config = normalize_saved_launch(service.launch_config) if restart else None
        snapshots.append(
            {
                "previous_id": service.id,
                "workload_id": service.container_id,
                "stopped": False,
                "config": config.model_dump(mode="json")
                if config is not None
                else None,
                "replacement_id": None,
                "previous_config": service.launch_config,
            }
        )
    if operation is None:
        operation = DeploymentMaintenance(id=1)
        session.add(operation)
    operation.revision = revision
    operation.phase = "preparing"
    operation.monitors = snapshots
    operation.updated_at = datetime.now(UTC)
    await session.commit()
    return operation


async def reserve(session, revision: str) -> dict:
    """Gate mutations before deployment quiesces writers or applies migration 010."""
    await lock_collection_configuration(session)
    if (
        await session.scalar(text("SELECT to_regclass('deployment_maintenance')"))
        is None
    ):
        if await session.scalar(text("SELECT to_regclass('services')")) is not None:
            raise ValueError(
                "Initialize the deployment maintenance schema before reserving "
                "an existing database"
            )
        # A fresh cluster has no application intent or writers to arbitrate.
        # The infrastructure applies migrations before begin creates its gate.
        await session.commit()
        return {"phase": "uninitialized"}
    if (
        await session.scalar(
            text("SELECT to_regclass('monitoring_pipeline_activations')")
        )
        is not None
    ):
        await require_no_pipeline_activation(session)
    operation = await session.get(DeploymentMaintenance, 1)
    if operation is not None and operation.phase != "complete":
        if operation.revision != revision:
            raise ValueError("A different release requires recovery before deploying")
        await session.commit()
        return {"phase": operation.phase}
    if operation is None:
        operation = DeploymentMaintenance(
            id=1,
            revision=revision,
            phase="quiescing",
            monitors=[],
            updated_at=datetime.now(UTC),
        )
        session.add(operation)
    services = await session.scalars(
        select(MonitoringService).where(monitor_claim_condition())
    )
    operation.monitors = [
        {
            "previous_id": service.id,
            "workload_id": service.container_id,
            "config": service.launch_config,
            "stopped": False,
            "replacement_id": None,
        }
        for service in services
    ]
    operation.revision = revision
    operation.phase = "quiescing"
    operation.updated_at = datetime.now(UTC)
    await session.commit()
    return {"phase": operation.phase}


async def wait_stopped(workloads, workload_id: str, *, attempts: int = 120):
    for _ in range(attempts):
        try:
            service = await workloads.async_docker.run(
                workloads.async_docker.client.services.get, workload_id
            )
        except docker.errors.NotFound as exc:
            raise ValueError(
                "Cannot verify the retiring RADAR service; recovery is required"
            ) from exc
        if service.attrs["Spec"]["Mode"]["Replicated"]["Replicas"] != 0:
            raise ValueError("The retiring RADAR service must have zero replicas")
        # Swarm removes cancelled task records while scaling down. Poll the
        # service's current tasks, including retiring tasks, rather than stale IDs.
        tasks = await workloads.async_docker.run(
            workloads.async_docker.client.api.tasks,
            filters={"service": workload_id},
        )
        if all(task["Status"]["State"] in TERMINAL_TASKS for task in tasks):
            return
        await asyncio.sleep(1)
    raise ValueError("A retiring RADAR task did not stop; deployment remains blocked")


async def begin(session, orchestration, revision: str) -> dict:
    operation = await prepare_operation(session, orchestration.workloads, revision)
    if operation.phase != "preparing":
        return {"phase": operation.phase, "monitors": len(operation.monitors)}
    await prepare_release_monitors(session, operation, orchestration.workloads)
    snapshots = list(operation.monitors)
    for index, monitor in enumerate(snapshots):
        if not monitor["stopped"]:
            await stop_release_monitor(session, orchestration, monitor, revision)
            snapshots[index] = monitor | {"stopped": True}
            operation.monitors = list(snapshots)
            operation.updated_at = datetime.now(UTC)
            await session.commit()
    operation.phase = "stopped"
    operation.updated_at = datetime.now(UTC)
    await session.commit()
    return {"phase": operation.phase, "monitors": len(operation.monitors)}


async def stop_release_monitor(session, orchestration, monitor, revision):
    """Retire attached or pending intent, preserving the claim on uncertainty."""
    workload_id = monitor["workload_id"]
    if workload_id:
        try:
            workload = await orchestration.workloads.async_docker.run(
                orchestration.workloads.async_docker.client.services.get, workload_id
            )
        except docker.errors.NotFound:
            # A missing service may still have retiring task records.
            await orchestration.workloads.remove(workload_id)
        else:
            await orchestration.workloads.async_docker.run(workload.scale, 0)
            await wait_stopped(orchestration.workloads, workload_id)
    service = await session.get(MonitoringService, monitor["previous_id"])
    if service is not None and not await orchestration.stop_radar_service(
        container_name=service.container_name, deployment_revision=revision
    ):
        raise ValueError(
            "A retiring monitor could not stop; deployment remains blocked"
        )


async def resume(session, orchestration, revision: str) -> dict:
    await lock_collection_configuration(session)
    operation = await session.get(DeploymentMaintenance, 1)
    if operation is None or operation.revision != revision:
        raise ValueError("No matching deployment maintenance operation")
    if operation.phase not in {"stopped", "restarted"}:
        raise ValueError("Monitor stops must complete before restarting")
    snapshots = list(operation.monitors)
    await session.commit()
    for index, monitor in enumerate(snapshots):
        if monitor["config"] is None:
            continue
        arguments = {"deployment_revision": revision}
        if monitor.get("replacement_service_id"):
            arguments["execution_service_id"] = monitor["replacement_service_id"]
        service = await orchestration.create_radar_service(
            RadarStartConfig.model_validate(monitor["config"]), **arguments
        )
        await record_release_run(session, monitor, service)
        snapshots[index] = monitor | {"replacement_id": service.id}
        operation.monitors = list(snapshots)
        operation.updated_at = datetime.now(UTC)
        await session.commit()
    operation.phase = "restarted"
    await session.commit()
    return {
        "phase": operation.phase,
        "restarted": sum(m["replacement_id"] is not None for m in snapshots),
    }


async def verify_restarted(session, revision: str, *, lock: bool = False) -> dict:
    operation = await session.get(DeploymentMaintenance, 1)
    if operation is None or operation.revision != revision:
        raise ValueError("No matching deployment maintenance operation")
    if operation.phase not in {"restarted", "complete"}:
        raise ValueError("Monitors have not been restarted")
    for monitor in operation.monitors:
        if monitor["config"] is None:
            continue
        statement = (
            select(PipelineRun)
            .where(PipelineRun.service_id == monitor["replacement_id"])
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        run = await session.scalar(statement)
        service = await session.get(
            MonitoringService,
            monitor["replacement_id"],
            with_for_update=lock,
            populate_existing=True,
        )
        if (
            run is None
            or run.ended_at is not None
            or run.status == "failed"
            or service is None
            or not service.status
            or service.operational_updated_at is None
            or (datetime.now(UTC) - service.operational_updated_at).total_seconds()
            > 120
            or service.operational_stage in {"failed", "stopped", "degraded"}
        ):
            raise ValueError(
                "A restarted monitor is not reporting healthy runtime status"
            )
    return {"verified": len(operation.monitors)}


async def finish(session, revision: str) -> dict:
    await lock_collection_configuration(session)
    await verify_restarted(session, revision, lock=True)
    operation = await session.get(DeploymentMaintenance, 1)
    for monitor in operation.monitors:
        if monitor.get("replacement_id"):
            run = await session.scalar(
                select(PipelineRun)
                .where(PipelineRun.service_id == monitor["replacement_id"])
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if run is not None and run.ended_at is None:
                run.status = "running"
    operation.phase = "complete"
    operation.updated_at = datetime.now(UTC)
    await session.commit()
    return {"phase": "complete"}


async def run(action: str, revision: str) -> dict:
    sessions = get_async_session_local()
    async with sessions() as session:
        workloads = RadarWorkloadManager(get_async_docker())
        if action == "capture":
            return await capture_existing(session, workloads)
        if action == "reserve":
            return await reserve(session, revision)
        if action == "verify":
            for attempt in range(60):
                try:
                    return await verify_restarted(session, revision)
                except ValueError:
                    await session.rollback()
                    if attempt == 59:
                        raise
                    await asyncio.sleep(5)
        if action == "finish":
            return await finish(session, revision)
        if action == "status":
            operation = await session.get(DeploymentMaintenance, 1)
            return {
                "phase": operation.phase if operation else "complete",
                "revision": operation.revision if operation else None,
            }
        registry = ModelRegistryService()
        await registry.initialize(max_retries=1)
        orchestration = RadarOrchestrationService(session, registry)
        return await (
            begin(session, orchestration, revision)
            if action == "begin"
            else resume(session, orchestration, revision)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=["capture", "reserve", "begin", "resume", "verify", "finish", "status"],
    )
    parser.add_argument("revision")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("revision must be a full commit SHA")
    try:
        print(json.dumps(asyncio.run(run(args.action, args.revision))))
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
        raise SystemExit(1) from None
    except Exception:
        print(
            json.dumps(
                {"error": "Monitor maintenance failed; retry the recorded release."}
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
