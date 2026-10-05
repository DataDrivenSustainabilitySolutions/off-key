"""Private CLI for resumable release maintenance; run through trusted SSH only."""

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime

import docker
from off_key_core.db.base import get_async_session_local
from off_key_core.db.collection import lock_collection_configuration
from off_key_core.db.models import DeploymentMaintenance, MonitoringService
from off_key_core.schemas.radar import RadarStartConfig
from sqlalchemy import select

from .models.registry import ModelRegistryService
from .services.orchestration.radar import RadarOrchestrationService
from .services.orchestration.radar_workloads import (
    RadarWorkloadManager,
    get_async_docker,
)

TERMINAL_TASKS = {"shutdown", "complete", "failed", "rejected", "remove"}


def captured_configuration(name: str, environment: list[str]) -> dict:
    """One-time capture of pre-integration workers, excluding runtime credentials."""
    values = dict(value.split("=", 1) for value in environment if "=" in value)
    config = RadarStartConfig.model_validate(
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
    if operation is not None and operation.phase != "complete":
        raise ValueError("Finish the pending deployment before capturing configuration")
    services = await session.scalars(
        select(MonitoringService).where(MonitoringService.status.is_(True))
    )
    count = 0
    for service in services:
        if service.launch_config is not None:
            continue
        workload = await workloads.async_docker.run(
            workloads.async_docker.client.services.get, service.container_id
        )
        environment = workload.attrs["Spec"]["TaskTemplate"]["ContainerSpec"]["Env"]
        service.launch_config = captured_configuration(
            service.container_name, environment
        )
        count += 1
    await session.commit()
    return {"captured": count}


async def prepare_operation(session, workloads, revision: str):
    await lock_collection_configuration(session)
    operation = await session.get(DeploymentMaintenance, 1)
    if operation is not None and operation.phase != "complete":
        if operation.revision != revision:
            raise ValueError("A different release requires recovery before deploying")
        await session.commit()
        return operation
    snapshots = []
    services = await session.scalars(
        select(MonitoringService).where(MonitoringService.status.is_(True))
    )
    for service in services:
        restart = service.stop_requested_at is None
        if restart and service.launch_config is None:
            raise ValueError(
                "Capture existing active monitor configuration before cutover"
            )
        config = (
            RadarStartConfig.model_validate(service.launch_config) if restart else None
        )
        tasks = await workloads.async_docker.run(
            workloads.async_docker.client.api.tasks,
            filters={"service": service.container_id},
        )
        snapshots.append(
            {
                "previous_id": service.id,
                "workload_id": service.container_id,
                "tasks": [
                    task["ID"]
                    for task in tasks
                    if task["Status"]["State"] not in TERMINAL_TASKS
                ],
                "stopped": False,
                "config": config.model_dump(mode="json")
                if config is not None
                else None,
                "replacement_id": None,
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


async def wait_stopped(workloads, task_ids: list[str], *, attempts: int = 120):
    for _ in range(attempts):
        running = False
        for task_id in task_ids:
            try:
                task = await workloads.async_docker.run(
                    workloads.async_docker.client.api.inspect_task, task_id
                )
            except docker.errors.NotFound as exc:
                raise ValueError(
                    "Cannot verify a retiring RADAR task; recovery is required"
                ) from exc
            running |= task["Status"]["State"] not in TERMINAL_TASKS
        if not running:
            return
        await asyncio.sleep(1)
    raise ValueError("A retiring RADAR task did not stop; deployment remains blocked")


async def begin(session, orchestration, revision: str) -> dict:
    operation = await prepare_operation(session, orchestration.workloads, revision)
    if operation.phase != "preparing":
        return {"phase": operation.phase, "monitors": len(operation.monitors)}
    snapshots = list(operation.monitors)
    for index, monitor in enumerate(snapshots):
        if not monitor["stopped"]:
            workload = await orchestration.workloads.async_docker.run(
                orchestration.workloads.async_docker.client.services.get,
                monitor["workload_id"],
            )
            await orchestration.workloads.async_docker.run(workload.scale, 0)
            await wait_stopped(orchestration.workloads, monitor["tasks"])
            snapshots[index] = monitor | {"stopped": True}
            operation.monitors = list(snapshots)
            operation.updated_at = datetime.now(UTC)
            await session.commit()
        await orchestration.stop_radar_service(
            container_id=monitor["workload_id"], deployment_revision=revision
        )
    operation.phase = "stopped"
    operation.updated_at = datetime.now(UTC)
    await session.commit()
    return {"phase": operation.phase, "monitors": len(operation.monitors)}


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
        service = await orchestration.create_radar_service(
            RadarStartConfig.model_validate(monitor["config"]),
            deployment_revision=revision,
        )
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


async def verify_restarted(session, revision: str) -> dict:
    operation = await session.get(DeploymentMaintenance, 1)
    if operation is None or operation.revision != revision:
        raise ValueError("No matching deployment maintenance operation")
    if operation.phase not in {"restarted", "complete"}:
        raise ValueError("Monitors have not been restarted")
    for monitor in operation.monitors:
        if monitor["config"] is None:
            continue
        service = await session.get(MonitoringService, monitor["replacement_id"])
        if (
            service is None
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
    await verify_restarted(session, revision)
    operation = await session.get(DeploymentMaintenance, 1)
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
        "action", choices=["capture", "begin", "resume", "verify", "finish", "status"]
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
