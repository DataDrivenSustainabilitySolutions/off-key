"""Names and identity labels of TACTIC-managed RADAR and preflight services."""

from typing import Any

from ...config.config import get_radar_container_runtime_settings
from ...facades.docker import workload_labels
from .radar_environment import (
    build_radar_config_fingerprint,
    build_radar_controller_identity,
)


def radar_workload_name(service_id: str) -> str:
    return f"radar-{service_id}"


def preflight_workload_name(activation_id: str) -> str:
    return f"radar-preflight-{activation_id}"


def controller_id(database_url: str | None = None) -> str:
    """Scope cleanup to this deployment's database, by default the runtime one."""
    return build_radar_controller_identity(
        database_url or get_radar_container_runtime_settings().radar_database_url
    )


def radar_identity_labels(service_id: str, environment: dict[str, str]) -> dict:
    """Labels that tie a RADAR service to one persisted monitor generation."""
    return {
        "managed_by": "tactic",
        "service_type": "radar",
        "radar_service_id": service_id,
        "radar_lifecycle_version": environment["RADAR_LIFECYCLE_VERSION"],
        "radar_config_fingerprint": build_radar_config_fingerprint(environment),
        "radar_controller_id": controller_id(environment["RADAR_DATABASE_URL"]),
    }


def preflight_identity_labels(activation_id: str) -> dict:
    """Labels that tie a preflight job to its activation and deployment."""
    return {
        "managed_by": "tactic",
        "service_type": "radar_preflight",
        "pipeline_activation_id": activation_id,
        "radar_controller_id": controller_id(),
    }


def has_labels(workload: Any, expected: dict) -> bool:
    labels = workload_labels(workload)
    return all(labels.get(key) == value for key, value in expected.items())
