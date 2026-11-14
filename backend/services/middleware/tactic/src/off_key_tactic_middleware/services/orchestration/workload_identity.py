"""Names and identity labels of TACTIC-managed RADAR and preflight workloads."""

from typing import Any

from .radar_environment import build_radar_config_fingerprint


def radar_workload_name(service_id: str) -> str:
    return f"radar-{service_id}"


def preflight_workload_name(activation_id: str) -> str:
    return f"radar-preflight-{activation_id}"


def radar_identity_labels(service_id: str, environment: dict[str, str]) -> dict:
    """Labels that tie a RADAR workload to one persisted monitor generation."""
    return {
        "managed_by": "tactic",
        "service_type": "radar",
        "radar_service_id": service_id,
        "radar_lifecycle_version": environment["RADAR_LIFECYCLE_VERSION"],
        "radar_config_fingerprint": build_radar_config_fingerprint(environment),
    }


def preflight_identity_labels(activation_id: str) -> dict:
    """Labels that tie a preflight job to its activation."""
    return {
        "managed_by": "tactic",
        "service_type": "radar_preflight",
        "pipeline_activation_id": activation_id,
    }


def workload_labels(workload: Any) -> dict[str, str]:
    """A workload's labels, or an empty mapping."""
    return dict(getattr(workload, "labels", None) or {})


def has_labels(workload: Any, expected: dict) -> bool:
    labels = workload_labels(workload)
    return all(labels.get(key) == value for key, value in expected.items())
