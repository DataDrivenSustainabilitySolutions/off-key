"""Keep real user/configuration/data/monitor state across a production redeploy.

The volume cutover runs the actual Ansible backup and TimescaleDB restore tasks.
The next identical deployment checks that retries do not duplicate workers.
"""

import json
import os
import subprocess
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from paho.mqtt import publish
from paho.mqtt.client import CallbackAPIVersion
from paho.mqtt.client import Client as MQTTClient

from tests.support.deployment import wait_until_service_accepts_data
from tests.support.integration_catalogue import (
    add_recorded_entity,
    remove_recorded_entity,
)

pytestmark = [
    pytest.mark.deployment,
    pytest.mark.skipif(
        os.getenv("OFFKEY_DEPLOYMENT_REHEARSAL") != "1",
        reason="requires the disposable production Swarm rehearsal",
    ),
]


def wait_for_measurement(client, entity, value):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        response = client.get(
            f"/v1/telemetry/{entity.entity_id}/data",
            params={"type": entity.keys["temperature"]},
        )
        response.raise_for_status()
        points = response.json()
        if any(point["value"] == value for point in points):
            return points
        time.sleep(1)
    pytest.fail(f"Measurement {value} did not reach persistent storage")


def get_json(client, path, **kwargs):
    response = client.get(path, **kwargs)
    response.raise_for_status()
    return response.json()


def refresh_authentication(client):
    # The production browser setup creates this disposable operator account.
    # A redeployment can outlive its original JWT even though the member persists.
    response = client.post(
        "/v1/auth/login",
        json={
            "email": os.getenv("SUPERUSER_MAIL", "admin@example.com"),
            "password": os.getenv("E2E_AUTH_PASSWORD", "PlaywrightPass123!"),
        },
    )
    response.raise_for_status()
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"


def wait_for_activation(client, identifier):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        progress = get_json(client, f"/v1/monitors/pipeline-activations/{identifier}")
        if progress["phase"] == "succeeded":
            return progress
        if progress["phase"] in {"failed", "cancelled"}:
            pytest.fail(f"Graph activation did not succeed: {progress}")
        time.sleep(1)
    pytest.fail(f"Graph activation did not finish within 180 seconds: {progress}")


def graph_definition(catalog):
    definition = deepcopy(
        next(item for item in catalog["templates"] if item["id"] == "adaptive_stream")[
            "definition"
        ]
    )
    definition["input_slots"] = [
        {"id": "processed", "label": "Processed current"},
        {"id": "raw", "label": "Raw temperature"},
    ]
    definition["nodes"][1]["params"] = {
        "num_trees": 4,
        "max_leaf_samples": 4,
        "window_size": 128,
        "seed": 42,
    }
    definition["nodes"][1:1] = [
        {
            "id": "selected",
            "kind": "transform",
            "component": "features.select",
            "params": {"features": ["processed"]},
        },
        {"id": "scaled", "kind": "transform", "component": "adaptive.standard_scaler"},
        {
            "id": "raw",
            "kind": "transform",
            "component": "features.select",
            "params": {"features": ["raw"]},
        },
        {"id": "joined", "kind": "merge", "component": "features.merge"},
    ]
    definition["edges"] = [
        {"source": source, "target": target, "order": order}
        for source, target, order in (
            ("input", "selected", 0),
            ("selected", "scaled", 0),
            ("input", "raw", 0),
            ("scaled", "joined", 0),
            ("raw", "joined", 1),
            ("joined", "detector", 0),
            ("detector", "policy", 0),
            ("policy", "output", 0),
        )
    ]
    definition["settings"].update(training_window_size=4, calibration_window_size=2)
    return definition


@dataclass
class SavedGraph:
    display_name: str
    design: dict
    revision: dict
    initial_run: dict
    layout: dict
    activation_id: str
    run_ids: list[str]
    service_ids: list[str]


def exercise_graph(client, entity, service_id, run_id, batch):
    """Send real source data and await one coherent operational observation."""
    wait_until_service_accepts_data(client, service_id)
    publisher = MQTTClient(
        CallbackAPIVersion.VERSION2, client_id=f"rehearsal-graph-{service_id}"
    )
    publisher.connect(
        os.getenv("E2E_SOURCE_MQTT_HOST", "localhost"),
        int(os.getenv("E2E_SOURCE_MQTT_PORT", "1884")),
    )
    publisher.loop_start()
    try:
        # Pace the frames across several diagnostic sampling intervals. Each
        # release starts a new run, which must warm up and calibrate for itself.
        for index in range(30):
            for key, value in (
                ("current", 1.0 + batch + index / 100),
                ("temperature", 20.0 + batch + index / 100),
            ):
                message = publisher.publish(entity.topics[key], str(value), qos=1)
                message.wait_for_publish(timeout=5)
                assert message.is_published()
            time.sleep(0.1)
    finally:
        publisher.disconnect()
        publisher.loop_stop()
    deadline = time.monotonic() + 120
    state = None
    while time.monotonic() < deadline:
        state = get_json(client, f"/v1/monitors/{service_id}/pipeline-state")
        if state:
            assert state["run_id"] == run_id
            assert state["phase"] != "failed", state
            learning = state.get("adaptive_learning", {})
            observation = state.get("observation")
            if (
                learning.get("state") == "operational"
                and observation is not None
                and observation["passes"]["score"]["detector"]["state"] == "ready"
            ):
                assert learning["ready"]
                assert learning["model_updates"] >= 8
                assert state["sequence_number"] >= observation["sequence_number"] >= 8
                assert state["nodes"]["detector"]["score_count"] > 0
                assert len(observation["input_timestamps"]) == 2
                score = observation["passes"]["score"]
                assert (
                    1.0 + batch
                    <= score["input"]["output"]["processed"]
                    <= (1.29 + batch)
                )
                assert (
                    20.0 + batch <= score["input"]["output"]["raw"] <= (20.29 + batch)
                )
                assert score["detector"]["input"] == score["joined"]["output"]
                assert set(score["detector"]["input"]) == {"processed", "raw"}
                assert (
                    score["detector"]["input"]["raw"]
                    == score["raw"]["output"]["raw"]
                    == score["input"]["output"]["raw"]
                )
                return
        time.sleep(1)
    pytest.fail(f"Restored graph did not process coherent source data: {state}")


def create_saved_graph(client, entity):
    catalog = get_json(client, "/v1/monitors/pipelines/catalog")
    assert catalog["authoring_enabled"]
    definition = graph_definition(catalog)
    layout = {
        "nodes": {
            node["id"]: {"x": index * 225 + 17, "y": index % 2 * 125 + 31}
            for index, node in enumerate(definition["nodes"])
        },
        "viewport": {"x": 23, "y": 47, "zoom": 0.8},
    }
    display_name = "Saved graph " + entity.device_id
    created = client.post(
        "/v1/monitors/pipelines",
        json={"name": display_name, "definition": definition, "layout": layout},
    )
    created.raise_for_status()
    design = created.json()
    published = client.post(
        f"/v1/monitors/pipelines/{design['id']}/revisions",
        json={"expected_version": design["version"]},
    )
    published.raise_for_status()
    revision = published.json()
    activated = client.post(
        "/v1/monitors/pipeline-activations",
        json={
            "revision_id": revision["id"],
            "bindings": dict(zip(("processed", "raw"), entity.stream_ids, strict=True)),
            "display_name": display_name,
            "idempotency_key": "rehearsal-" + entity.device_id,
        },
    )
    activated.raise_for_status()
    activation = wait_for_activation(client, activated.json()["id"])
    exercise_graph(
        client, entity, activation["service_id"], activation["run_id"], batch=0
    )
    view = get_json(client, f"/v1/monitors/{activation['service_id']}/pipeline")
    assert {
        item["slot_id"]: item["reading_id"]
        for item in view["run"]["execution"]["bindings"]
    } == dict(zip(("processed", "raw"), entity.stream_ids, strict=True))
    assert {
        item["accepted_topic"] for item in view["run"]["execution"]["bindings"]
    } == set(entity.accepted_topics)
    # A per-run arrangement is independent from the published design layout.
    changed_layout = deepcopy(view["layout"])
    changed_layout["nodes"]["joined"]["x"] += 83
    arranged = client.put(
        f"/v1/monitors/{activation['service_id']}/pipeline-layout", json=changed_layout
    )
    arranged.raise_for_status()
    return SavedGraph(
        display_name=display_name,
        design=get_json(client, f"/v1/monitors/pipelines/{design['id']}"),
        revision=revision,
        initial_run=view["run"],
        layout=arranged.json(),
        activation_id=activation["id"],
        run_ids=[view["run"]["id"]],
        service_ids=[activation["service_id"]],
    )


def assert_one_graph_workload(saved, expected_image):
    identifiers = subprocess.run(
        [
            "docker",
            "service",
            "ls",
            "--quiet",
            "--filter",
            "label=managed_by=tactic",
            "--filter",
            "label=service_type=radar",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.split()
    assert identifiers, "The production graph has no Swarm workload"
    labels = subprocess.run(
        [
            "docker",
            "service",
            "inspect",
            "--format",
            "{{json .Spec.Labels}}",
            *identifiers,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.splitlines()
    matches = [
        identifier
        for identifier, encoded in zip(identifiers, labels, strict=True)
        if json.loads(encoded).get("radar_service_id") in saved.service_ids
    ]
    assert len(matches) == 1, "Retired graph workers survived deployment"
    actual_image = subprocess.run(
        [
            "docker",
            "service",
            "inspect",
            "--format",
            "{{.Spec.TaskTemplate.ContainerSpec.Image}}",
            matches[0],
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    assert actual_image.split("@")[-1] == expected_image.split("@")[-1]
    states = subprocess.run(
        [
            "docker",
            "service",
            "ps",
            matches[0],
            "--filter",
            "desired-state=running",
            "--format",
            "{{.CurrentState}}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.splitlines()
    assert [state.split()[0] for state in states] == ["Running"]


def assert_graph_restored(client, entity, saved, workers, release):
    assert not get_json(client, "/v1/monitors/pipelines/catalog")["authoring_enabled"]
    matches = [item for item in workers if item["display_name"] == saved.display_name]
    assert len(matches) == 1
    service_id = matches[0]["id"]
    assert service_id not in saved.service_ids
    view = get_json(client, f"/v1/monitors/{service_id}/pipeline")
    run = view["run"]
    assert not view["legacy"]
    assert run["status"] == "running" and run["ended_at"] is None
    assert run["id"] not in saved.run_ids
    assert run["predecessor_run_id"] == saved.run_ids[-1]
    assert view["layout"] == saved.layout
    assert view["definition"] == saved.revision["definition"]
    assert run["binding_metadata"] == saved.initial_run["binding_metadata"]
    assert (
        run["execution"]["fingerprint"] == saved.initial_run["execution"]["fingerprint"]
    )
    exercise_graph(client, entity, service_id, run["id"], batch=len(saved.run_ids))
    saved.run_ids.append(run["id"])
    saved.service_ids.append(service_id)
    assert [item["id"] for item in view["history"]] == list(reversed(saved.run_ids))
    for ancestor in view["history"]:
        assert ancestor["revision_id"] == saved.revision["id"]
        retained = get_json(client, f"/v1/monitors/{ancestor['service_id']}/pipeline")[
            "run"
        ]
        assert retained["id"] == ancestor["id"]
        assert (
            retained["execution"]["bindings"]
            == saved.initial_run["execution"]["bindings"]
        )
    assert (
        get_json(client, f"/v1/monitors/pipelines/{saved.design['id']}") == saved.design
    )
    assert (
        get_json(
            client,
            f"/v1/monitors/pipelines/{saved.design['id']}/revisions/{saved.revision['id']}",
        )
        == saved.revision
    )
    assert_one_graph_workload(saved, release["images"]["mqtt_radar"])


def test_redeploy_restores_state_rolls_back_compatible_binaries_and_resumes_once():
    directory = Path(os.environ["OFFKEY_REHEARSAL_DIR"])
    root = Path(__file__).resolve().parents[2]
    headers = {"Authorization": f"Bearer {os.environ['E2E_AUTH_TOKEN']}"}
    with httpx.Client(
        base_url=os.getenv("E2E_GATEWAY_URL", "http://localhost:8000"),
        headers=headers,
        timeout=210,
    ) as client:
        refresh_authentication(client)
        member = get_json(client, "/v1/members/me")
        entity = add_recorded_entity(
            client, label="Rehearsal entity", keys=("temperature",)
        )
        graph_entity = add_recorded_entity(
            client, label="Rehearsal graph entity", keys=("current", "temperature")
        )
        worker_name = "rehearsal-" + entity.device_id
        snapshot = get_json(client, "/v1/system")
        topic = entity.topics["temperature"]
        graph = None
        completed = False
        try:
            graph = create_saved_graph(client, graph_entity)
            publish.single(topic, "23.5", hostname="localhost", port=1884, qos=1)
            saved_data = wait_for_measurement(client, entity, 23.5)
            started = client.post(
                "/v1/monitors/start",
                json={
                    "container_name": worker_name,
                    "display_name": "Saved monitoring service",
                    "mqtt_topics": list(entity.accepted_topics),
                    "model_type": "pyod_iforest",
                },
            )
            started.raise_for_status()
            wait_until_service_accepts_data(client, started.json()["service_id"])
            current_release = json.loads(
                (directory / "production-release.json").read_text()
            )["release"]
            compatible = json.loads(
                (directory / "compatible-release.json").read_text()
            )["release"]
            assert (
                compatible["application_revision"]
                != current_release["application_revision"]
            )
            for name in (
                "api",
                "tactic",
                "mqtt_proxy",
                "mqtt_radar",
                "db_sync",
                "frontend",
            ):
                assert compatible["images"][name] != current_release["images"][name]
            # Restore B's data, run older pipeline-compatible A, then return to B.
            # The rollback keeps the live schema/data; no pre-feature image is used.
            for restore, target, expected in (
                (True, "current", current_release),
                (False, "compatible", compatible),
                (False, "current", current_release),
            ):
                command = [
                    "uv",
                    "run",
                    "--frozen",
                    "--project",
                    str(root / "infra"),
                    "python",
                    str(root / "infra/tests/swarm_smoke.py"),
                    "redeploy",
                    "--directory",
                    str(directory),
                    "--release",
                    target,
                ]
                if restore:
                    command.append("--restore")
                subprocess.run(command, cwd=root, check=True, timeout=1200)
                refresh_authentication(client)
                assert get_json(client, "/v1/members/me") == member
                current = client.get("/v1/system").json()
                assert current["revision"] == snapshot["revision"]
                assert current["document"] == snapshot["document"]
                assert current["runtime"]["bindings"] == snapshot["runtime"]["bindings"]
                assert (
                    current["runtime"]["collection_revision"]
                    == snapshot["runtime"]["collection_revision"]
                )
                assert (
                    client.get(
                        f"/v1/telemetry/{entity.entity_id}/data",
                        params={"type": entity.keys["temperature"]},
                    ).json()
                    == saved_data
                )
                monitors = client.get(
                    "/v1/monitors/all",
                    params={"active_only": "true", "include_docker_status": "true"},
                )
                monitors.raise_for_status()
                workers = [
                    item
                    for item in monitors.json()
                    if item["container_name"] == worker_name
                ]
                assert len(workers) == 1
                assert workers[0]["display_name"] == "Saved monitoring service"
                wait_until_service_accepts_data(client, workers[0]["id"])
                assert_graph_restored(
                    client, graph_entity, graph, monitors.json(), expected
                )
                record = json.loads((directory / "stack/release.json").read_text())
                assert (
                    record["application_revision"] == expected["application_revision"]
                )
                assert not (directory / "stack/release-maintenance.json").exists()
                evidence_path = directory / "binary-rollback-evidence.json"
                evidence = json.loads(evidence_path.read_text())
                evidence["cutovers"][-1]["graph"] = {
                    "revision_id": graph.revision["id"],
                    "run_id": graph.run_ids[-1],
                    "history_run_ids": graph.run_ids,
                    "binding_fingerprint": graph.initial_run["execution"][
                        "fingerprint"
                    ],
                    "layout_preserved": True,
                    "binding_metadata_preserved": True,
                    "coherent_score_observed": True,
                    "one_owned_worker": True,
                    "authoring_enabled": False,
                }
                evidence_path.write_text(json.dumps(evidence, indent=2))
            assert list((directory / "backups/postgres").glob("*/*.dump"))
            publish.single(topic, "24.5", hostname="localhost", port=1884, qos=1)
            wait_for_measurement(client, entity, 24.5)
            completed = True
        finally:
            # Preserve failed cutovers and activation state for diagnostics.
            # Workflow cleanup always removes the disposable production stack.
            if (
                completed
                and not (directory / "stack/release-maintenance.json").exists()
            ):
                monitors = client.get(
                    "/v1/monitors/all", params={"include_docker_status": "false"}
                ).json()
                for worker in monitors:
                    if worker["container_name"] == worker_name or (
                        graph is not None
                        and worker["display_name"] == graph.display_name
                    ):
                        client.delete(f"/v1/monitors/{worker['id']}").raise_for_status()
                # Incomplete graph activation retains its inputs until the
                # workflow's production-stack cleanup, preserving its error.
                if graph is not None:
                    remove_recorded_entity(client, graph_entity)
                remove_recorded_entity(client, entity)
