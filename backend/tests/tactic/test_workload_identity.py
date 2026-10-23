"""Workload names, identity labels and Swarm task states are pinned in one place."""

from types import SimpleNamespace

import pytest
from off_key_tactic_middleware.facades import docker as docker_facade
from off_key_tactic_middleware.services.orchestration import workload_identity


@pytest.fixture
def identity(monkeypatch):
    monkeypatch.setattr(
        workload_identity,
        "build_radar_controller_identity",
        lambda database_url: f"controller:{database_url}",
    )
    monkeypatch.setattr(
        workload_identity,
        "get_radar_container_runtime_settings",
        lambda: SimpleNamespace(radar_database_url="postgresql://runtime/db"),
    )
    monkeypatch.setattr(
        workload_identity, "build_radar_config_fingerprint", lambda env: "print"
    )
    return workload_identity


def test_names_and_identity_labels_are_stable(identity):
    assert identity.radar_workload_name("abc") == "radar-abc"
    assert identity.preflight_workload_name("act") == "radar-preflight-act"
    environment = {
        "RADAR_LIFECYCLE_VERSION": "3",
        "RADAR_DATABASE_URL": "postgresql://worker/db",
    }
    assert identity.radar_identity_labels("abc", environment) == {
        "managed_by": "tactic",
        "service_type": "radar",
        "radar_service_id": "abc",
        "radar_lifecycle_version": "3",
        "radar_config_fingerprint": "print",
        "radar_controller_id": "controller:postgresql://worker/db",
    }
    assert identity.preflight_identity_labels("act") == {
        "managed_by": "tactic",
        "service_type": "radar_preflight",
        "pipeline_activation_id": "act",
        "radar_controller_id": "controller:postgresql://runtime/db",
    }


@pytest.mark.parametrize(
    ("attrs", "labels"),
    [
        ({"Spec": {"Labels": {"a": "1"}}}, {"a": "1"}),
        ({"Spec": {"Labels": None}}, {}),
        ({"Spec": {}}, {}),
        (None, {}),
    ],
)
def test_labels_tolerate_missing_specs(identity, attrs, labels):
    workload = SimpleNamespace(attrs=attrs)
    assert docker_facade.workload_labels(workload) == labels
    assert identity.has_labels(workload, labels)
    assert not identity.has_labels(workload, {"a": "2"})


def test_swarm_task_state_sets_are_pinned():
    done = {"shutdown", "complete", "failed", "rejected", "remove"}
    assert done == docker_facade.SWARM_TASK_DONE
    assert done | {"completed"} == docker_facade.SWARM_TASK_SHUTDOWN_DONE
    assert done | {"orphaned"} == docker_facade.SWARM_TASK_STARTUP_FAILED


def test_latest_task_status_uses_the_newest_task():
    tasks = [
        {"CreatedAt": "2", "Status": {"State": "Running"}},
        {"CreatedAt": "1", "Status": {"State": "failed"}},
        "ignored",
    ]
    assert docker_facade.latest_task_status(tasks) == {"State": "Running"}
    assert docker_facade.latest_task_status([]) is None
    assert docker_facade._extract_latest_workload_state(tasks) == "running"
