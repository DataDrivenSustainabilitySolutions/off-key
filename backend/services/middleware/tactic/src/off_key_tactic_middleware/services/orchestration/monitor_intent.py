"""Durable stop and delete transitions of a monitoring service row.

Callers keep their own filters, fences and lock order; these primitives only
spell each transition once.
"""

from datetime import UTC, datetime
from typing import Any, cast

from off_key_core.db.models import MonitoringService, MqttTopic
from off_key_core.db.pipeline_locks import complete_stopped_runs
from off_key_core.schemas.radar import RadarOperationalStatus
from sqlalchemy import CursorResult, delete

COLLECTION_CHANGED_DETAIL = "Collection changed. Restart with fresh calibration."


def request_stop_values() -> dict:
    """Column values for a bulk UPDATE that records stop intent."""
    return {
        "desired_state": "stopped",
        "stop_requested_at": datetime.now(UTC),
        "lifecycle_version": MonitoringService.lifecycle_version + 1,
    }


def next_lifecycle_version(service: MonitoringService) -> int:
    return (getattr(service, "lifecycle_version", None) or 1) + 1


def mark_deleting(service: MonitoringService, *, hold_claim: bool = False) -> None:
    """Record delete intent; holding the claim keeps the inputs reserved."""
    service.desired_state = "deleted"
    service.lifecycle_version = next_lifecycle_version(service)
    service.stop_requested_at = datetime.now(UTC)
    if hold_claim:
        service.status = True


async def retire_workload(
    workloads, service_id, workload_id, config_fingerprint
) -> bool:
    """Remove a worker and, for intent-tracked rows, any unknown create outcome.

    Reconciliation keeps its own branch: it builds the manager lazily.
    """
    if config_fingerprint:
        return await workloads.remove_intent(service_id, workload_id)
    return await workloads.remove(workload_id)


async def purge_service_rows(session, service_ids: list[str]) -> int:
    """Close the services' runs and delete their topic and service rows."""
    if not service_ids:
        return 0
    await complete_stopped_runs(session, service_ids)
    await session.execute(
        delete(MqttTopic).where(MqttTopic.service_id.in_(service_ids))
    )
    result = cast(
        CursorResult[Any],
        await session.execute(
            delete(MonitoringService).where(MonitoringService.id.in_(service_ids))
        ),
    )
    return int(result.rowcount or 0)


def complete_stop(
    service: MonitoringService, detail: str = COLLECTION_CHANGED_DETAIL
) -> None:
    """Complete a durable stop request after workload removal succeeds."""
    status = RadarOperationalStatus(
        stage="stopped", detail=detail, updated_at=datetime.now(UTC)
    )
    service.status = False
    service.desired_state = "stopped"
    service.lifecycle_version = next_lifecycle_version(service)
    service.operational_stage = status.stage
    service.operational_updated_at = status.updated_at
    service.operational_status = status.model_dump(mode="json", exclude_none=True)
    service.stop_requested_at = None
