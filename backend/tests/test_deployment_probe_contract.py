"""The deployment readiness probe reads the real collection runtime shape.

It also keeps its literal 'applied' status in step with core's status schema.

infra/scripts/check_application.py runs inside the deployed proxy image and its
infra unit tests use stand-ins, so this pins it to the backend's own models.
"""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from off_key_core.schemas.collection_status import (
    COLLECTION_APPLIED,
    COLLECTION_APPLYING,
    COLLECTION_ERROR,
    COLLECTION_PREPARED,
    INGRESS_APPLIED,
    INGRESS_CONNECTING,
    is_applied,
)
from off_key_core.schemas.system import SystemDocument
from off_key_core.schemas.system_collection import (
    SystemCollectionDefinition,
    build_bindings,
)

PROBE = Path(__file__).resolve().parents[2] / "infra/scripts/check_application.py"


def probe():
    spec = importlib.util.spec_from_file_location("check_application", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def runtime(*, revision, selected, now):
    document = SystemDocument.model_validate(
        {
            "connections": [{"id": "broker", "label": "Lab", "host": "127.0.0.1"}],
            "streams": [
                {
                    "id": "temperature",
                    "label": "Temperature",
                    "connection_id": "broker",
                    "topic": "lab/readings",
                    "payload_pointer": "/temperature",
                    "policy": {"mode": "original" if selected else "off"},
                }
            ],
        }
    )
    heartbeat = {
        "revision": revision,
        "status": "applied",
        "checked_at": now.isoformat(),
    }
    return SimpleNamespace(
        revision=revision,
        catalog=SystemCollectionDefinition(
            document=document, bindings=build_bindings(document), generation="probe"
        ),
        collection=dict(heartbeat),
        ingress=heartbeat | {"sources": {"broker": {"state": "connected"}}},
    )


def test_probe_accepts_a_connected_selected_broker_from_the_real_model():
    now = datetime.now(UTC)
    result = probe().check_collection(runtime(revision=3, selected=True, now=now), now)
    assert result["revision"] == 3


def test_probe_reports_a_selected_broker_without_ingress_by_its_label():
    now = datetime.now(UTC)
    snapshot = runtime(revision=3, selected=True, now=now)
    snapshot.ingress["sources"] = {}
    with pytest.raises(ValueError, match=r"Lab \(127\.0\.0\.1:1883\)"):
        probe().check_collection(snapshot, now)


def test_probe_skips_brokers_before_the_first_save():
    now = datetime.now(UTC)
    empty = SimpleNamespace(
        revision=0,
        catalog=SystemCollectionDefinition(document=SystemDocument(), bindings={}),
        collection={},
        ingress={},
    )
    assert probe().check_collection(empty, now) == {
        "revision": 0,
        "selected_sensors": 0,
    }


@pytest.mark.parametrize(
    ("collection", "ingress", "accepted"),
    [
        (COLLECTION_APPLIED, INGRESS_APPLIED, True),
        (COLLECTION_APPLYING, INGRESS_APPLIED, False),
        (COLLECTION_PREPARED, INGRESS_APPLIED, False),
        (COLLECTION_ERROR, INGRESS_APPLIED, False),
        (COLLECTION_APPLIED, INGRESS_CONNECTING, False),
    ],
)
def test_probe_accepts_only_the_statuses_core_calls_applied(
    collection, ingress, accepted
):
    now = datetime.now(UTC)
    snapshot = runtime(revision=3, selected=True, now=now)
    snapshot.collection["status"] = collection
    snapshot.ingress["status"] = ingress
    assert is_applied(snapshot.collection, 3) is (collection == COLLECTION_APPLIED)
    if accepted:
        probe().check_collection(snapshot, now)
    else:
        with pytest.raises(ValueError, match="has not applied catalog revision 3"):
            probe().check_collection(snapshot, now)
