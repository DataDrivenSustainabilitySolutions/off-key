"""Private CLI for resumable release maintenance; run through trusted SSH only."""

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime

from off_key_core.db.base import get_async_session_local
from off_key_core.db.collection import lock_collection_configuration
from off_key_core.db.models import DeploymentMaintenance, MonitoringService, PipelineRun
from off_key_core.db.pipeline_claims import (
    monitor_claim_condition,
    require_no_pipeline_activation,
)
from off_key_core.schemas.radar import RadarStartConfig
from sqlalchemy import select, text

from .services.orchestration.radar import RadarOrchestrationService
from .services.orchestration.radar_status import (
    RUNTIME_STATUS_STALE_AFTER_SECONDS,
    heartbeat_age_seconds,
)
from .services.pipelines.release import (
    normalize_saved_launch,
    prepare_release_monitors,
    record_release_run,
)

# A saved launch can be restarted without reading the old workload.
_LAUNCH_KEYS = ("container_name", "mqtt_topics", "monitoring")


def _has_launch(configuration: dict) -> bool:
    return all(key in configuration for key in _LAUNCH_KEYS)


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
        if restart and not _has_launch(service.launch_config or {}):
            raise ValueError("An active monitor has no saved launch configuration")
        snapshot = {
            "previous_id": service.id,
            "workload_id": service.container_id,
            "stopped": False,
            "config": None,
            "replacement_id": None,
            "previous_config": service.launch_config,
        }
        if restart:
            snapshot["config"] = normalize_saved_launch(
                service.launch_config
            ).model_dump(mode="json")
        snapshots.append(snapshot)
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
    """Gate mutations before deployment quiesces writers or applies migrations."""
    await lock_collection_configuration(session)
    if (
        await session.scalar(text("SELECT to_regclass('deployment_maintenance')"))
        is None
    ):
        # A fresh, empty database has no application intent or writers to
        # arbitrate. The infrastructure installs the schema before begin
        # creates its gate.
        await session.commit()
        return {"phase": "uninitialized"}
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
            "active": service.stop_requested_at is None,
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
        # The pool ends the child; the row stays until the stop below removes it.
        await orchestration.workloads.request_stop(workload_id)
        await orchestration.workloads.wait_stopped(workload_id)
    service = await session.get(MonitoringService, monitor["previous_id"])
    if service is not None and not await orchestration.stop_radar_service(
        service.id, deployment_revision=revision
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
        await record_release_run(session, service)
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
        await verify_monitor(session, monitor["replacement_id"], lock=lock)
    return {"verified": len(operation.monitors)}


async def verify_monitor(session, service_id, *, lock: bool = False):
    statement = (
        select(PipelineRun)
        .where(PipelineRun.service_id == service_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        statement = statement.with_for_update()
    run = await session.scalar(statement)
    service = await session.get(
        MonitoringService,
        service_id,
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
        or heartbeat_age_seconds(service.operational_updated_at)
        > RUNTIME_STATUS_STALE_AFTER_SECONDS
        or service.operational_stage in {"failed", "stopped", "degraded"}
    ):
        raise ValueError("A restarted monitor is not reporting healthy runtime status")


async def verify_active(session) -> dict:
    services = (
        await session.scalars(
            select(MonitoringService.id).where(
                monitor_claim_condition(),
                MonitoringService.stop_requested_at.is_(None),
            )
        )
    ).all()
    for service_id in services:
        await verify_monitor(session, service_id)
    return {"verified": len(services)}


async def finish_static(session, revision: str) -> dict:
    """Complete the shared release reservation without stopping any monitor."""
    await lock_collection_configuration(session)
    operation = await session.get(DeploymentMaintenance, 1)
    if (
        operation is None
        or operation.revision != revision
        or operation.phase != "quiescing"
    ):
        raise ValueError("No matching unchanged static release reservation")
    for monitor in operation.monitors:
        if (
            "active" not in monitor
            or monitor["stopped"]
            or monitor["replacement_id"] is not None
        ):
            raise ValueError("A static release cannot complete a monitor cutover")
        if not monitor["active"]:
            continue
        service = await session.get(
            MonitoringService,
            monitor["previous_id"],
            with_for_update=True,
            populate_existing=True,
        )
        if service is None:
            raise ValueError(
                "An existing monitor is not reporting healthy runtime status"
            )
        if service.stop_requested_at is not None:
            continue
        await verify_monitor(session, monitor["previous_id"], lock=True)
        if service.container_id != monitor["workload_id"]:
            raise ValueError("A static release replaced an existing monitor worker")
    operation.phase = "complete"
    operation.updated_at = datetime.now(UTC)
    await session.commit()
    return {"phase": "complete"}


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


async def abort(session, revision: str) -> dict:
    """Reopen catalog and monitor changes without verifying the restarted monitors.

    For a release that cannot finish: monitors it restarted keep running as they
    are and their runs count as running; monitors it stopped and did not restart
    stay stopped. Their saved configurations are reported so they can be started
    again from the workbench.
    """
    await lock_collection_configuration(session)
    operation = await session.get(DeploymentMaintenance, 1)
    if operation is None or operation.revision != revision:
        raise ValueError("No matching deployment maintenance operation")
    if operation.phase == "complete":
        return {"phase": "complete", "aborted": False}
    restarted, not_restarted = [], []
    for monitor in operation.monitors:
        replacement = monitor.get("replacement_id")
        if replacement:
            restarted.append(replacement)
            run = await session.scalar(
                select(PipelineRun)
                .where(PipelineRun.service_id == replacement)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if run is not None and run.ended_at is None and run.status != "failed":
                run.status = "running"
        elif monitor.get("stopped") or operation.phase in {"stopped", "restarted"}:
            not_restarted.append(monitor["previous_id"])
    aborted_phase = operation.phase
    operation.phase = "complete"
    operation.updated_at = datetime.now(UTC)
    await session.commit()
    return {
        "phase": "complete",
        "aborted": True,
        "aborted_phase": aborted_phase,
        "restarted": restarted,
        "not_restarted": not_restarted,
    }


async def run(action: str, revision: str) -> dict:
    sessions = get_async_session_local()
    async with sessions() as session:
        actions = {
            "reserve": reserve,
            "finish": finish,
            "finish-static": finish_static,
            "abort": abort,
        }
        if action in actions:
            return await actions[action](session, revision)
        if action in {"verify", "verify-active"}:
            for attempt in range(60):
                try:
                    return await (
                        verify_active(session)
                        if action == "verify-active"
                        else verify_restarted(session, revision)
                    )
                except ValueError:
                    await session.rollback()
                    if attempt == 59:
                        raise
                    await asyncio.sleep(5)
        if action == "status":
            operation = await session.get(DeploymentMaintenance, 1)
            return {
                "phase": operation.phase if operation else "complete",
                "revision": operation.revision if operation else None,
            }
        orchestration = RadarOrchestrationService(session)
        return await (
            begin(session, orchestration, revision)
            if action == "begin"
            else resume(session, orchestration, revision)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "reserve",
            "begin",
            "resume",
            "verify",
            "verify-active",
            "finish",
            "finish-static",
            "abort",
            "status",
        ],
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
