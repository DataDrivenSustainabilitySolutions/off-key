"""Project persisted and Docker state into the public RADAR status contract."""

from datetime import UTC, datetime
from typing import Any

from off_key_core.db.models import MonitoringService
from off_key_core.schemas.radar import RadarOperationalStatus

from .time_utils import coerce_utc

FAILED_WORKLOAD_STATES = {"dead", "error", "exited", "failed", "rejected"}
STOPPED_WORKLOAD_STATES = {
    "complete",
    "completed",
    "no_container_id",
    "no_tasks",
    "not_found",
    "removed",
    "stopped",
}
TERMINAL_WORKLOAD_STATES = FAILED_WORKLOAD_STATES | STOPPED_WORKLOAD_STATES
RUNTIME_STATUS_STALE_AFTER_SECONDS = 120.0


def normalize_operational_status(service: MonitoringService) -> dict[str, Any]:
    """Normalize a persisted status payload into the current public contract."""
    raw_status = service.operational_status or {}
    if not isinstance(raw_status, dict):
        raw_status = {}

    updated_at = coerce_utc(
        raw_status.get("updated_at") or service.operational_updated_at
    )
    payload = {
        **raw_status,
        "stage": raw_status.get("stage")
        or service.operational_stage
        or ("starting" if service.status else "stopped"),
        "message_count": raw_status.get("message_count", 0),
        "processed_message_count": raw_status.get("processed_message_count", 0),
        "updated_at": updated_at,
        "is_stale": bool(raw_status.get("is_stale", False)),
    }
    return RadarOperationalStatus(**payload).model_dump(mode="json", exclude_none=True)


def derive_operational_status(
    service: MonitoringService,
    docker_status: str | None = None,
) -> dict[str, Any]:
    """Derive the externally visible status from persisted and Docker state."""
    status = normalize_operational_status(service)
    docker_state = (docker_status or "").strip().lower()

    if docker_state in FAILED_WORKLOAD_STATES:
        return _override_operational_status(
            status,
            "failed",
            f"Docker workload is {docker_state}",
            error=f"Docker workload is {docker_state}",
        )
    if docker_state in STOPPED_WORKLOAD_STATES:
        return _override_operational_status(
            status,
            "stopped",
            f"Docker workload is {docker_state}",
        )
    if not service.status:
        return _override_operational_status(status, "stopped", "Service stopped")

    if docker_state == "running":
        updated_at = coerce_utc(service.operational_updated_at)
        if updated_at is None:
            return _mark_operational_status_stale(
                status, "Runtime heartbeat has not arrived"
            )
        age_seconds = (datetime.now(UTC) - updated_at).total_seconds()
        if age_seconds > RUNTIME_STATUS_STALE_AFTER_SECONDS:
            return _mark_operational_status_stale(status, "Runtime heartbeat is stale")

    return status


def apply_terminal_operational_status(
    service: MonitoringService,
    docker_status: str,
) -> None:
    """Persist a terminal Docker state on an existing service model."""
    status = derive_operational_status(service, docker_status)
    service.operational_stage = status["stage"]
    service.operational_status = status
    service.operational_updated_at = coerce_utc(status.get("updated_at"))


def _override_operational_status(
    status: dict[str, Any],
    stage: str,
    detail: str,
    error: str | None = None,
) -> dict[str, Any]:
    payload = {
        **status,
        "stage": stage,
        "detail": detail,
        "error": error if error is not None else status.get("error"),
        "updated_at": datetime.now(UTC),
        "is_stale": False,
    }
    return RadarOperationalStatus(**payload).model_dump(mode="json", exclude_none=True)


def _mark_operational_status_stale(
    status: dict[str, Any],
    detail: str,
) -> dict[str, Any]:
    payload = {**status, "detail": detail, "is_stale": True}
    return RadarOperationalStatus(**payload).model_dump(mode="json", exclude_none=True)
