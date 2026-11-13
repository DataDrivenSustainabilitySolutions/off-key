"""Workload names and identity labels are pinned in one place."""

from types import SimpleNamespace

import pytest
from off_key_tactic_middleware.services.orchestration import workload_identity


@pytest.fixture
def identity(monkeypatch):
    monkeypatch.setattr(
        workload_identity, "build_radar_config_fingerprint", lambda env: "print"
    )
    return workload_identity


def test_names_and_identity_labels_are_stable(identity):
    assert identity.radar_workload_name("abc") == "radar-abc"
    assert identity.preflight_workload_name("act") == "radar-preflight-act"
    assert identity.radar_identity_labels("abc", {"RADAR_LIFECYCLE_VERSION": "3"}) == {
        "managed_by": "tactic",
        "service_type": "radar",
        "radar_service_id": "abc",
        "radar_lifecycle_version": "3",
        "radar_config_fingerprint": "print",
    }
    assert identity.preflight_identity_labels("act") == {
        "managed_by": "tactic",
        "service_type": "radar_preflight",
        "pipeline_activation_id": "act",
    }


@pytest.mark.parametrize(
    ("labels", "expected"),
    [({"a": "1"}, {"a": "1"}), (None, {}), ({}, {})],
)
def test_labels_tolerate_a_workload_without_labels(identity, labels, expected):
    workload = SimpleNamespace(labels=labels)
    assert identity.workload_labels(workload) == expected
    assert identity.has_labels(workload, expected)
    assert not identity.has_labels(workload, {"a": "2"})
    assert identity.workload_labels(object()) == {}
