"""Keep real user/configuration/data/monitor state across a production redeploy.

The volume cutover runs the actual Ansible backup and TimescaleDB restore tasks.
The next identical deployment checks that retries do not duplicate workers.
"""

import json
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from paho.mqtt import publish

from .integration_catalogue import add_recorded_entity, remove_recorded_entity
from .test_adaptive_lane_e2e import _wait_until_service_accepts_data

pytestmark = pytest.mark.skipif(
    os.getenv("OFFKEY_DEPLOYMENT_REHEARSAL") != "1",
    reason="requires the disposable production Swarm rehearsal",
)


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


def test_redeploy_restores_saved_state_and_resumes_one_monitor():
    directory = Path(os.environ["OFFKEY_REHEARSAL_DIR"])
    root = Path(__file__).resolve().parents[2]
    headers = {"Authorization": f"Bearer {os.environ['E2E_AUTH_TOKEN']}"}
    with httpx.Client(
        base_url=os.getenv("E2E_GATEWAY_URL", "http://localhost:8000"),
        headers=headers,
        timeout=210,
    ) as client:
        member = client.get("/v1/members/me")
        member.raise_for_status()
        entity = add_recorded_entity(
            client, label="Rehearsal entity", keys=("temperature",)
        )
        worker_name = "rehearsal-" + entity.device_id
        snapshot = client.get("/v1/system").json()
        topic = entity.topics["temperature"]
        try:
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
            _wait_until_service_accepts_data(client, started.json()["service_id"])
            verified = json.loads((directory / "stack/release.json").read_text())
            for restore in (True, False, False):
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
                ]
                if restore:
                    command.append("--restore")
                subprocess.run(command, cwd=root, check=True, timeout=1200)
                assert client.get("/v1/members/me").json() == member.json()
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
                _wait_until_service_accepts_data(client, workers[0]["id"])
                record = json.loads((directory / "stack/release.json").read_text())
                assert (
                    record["application_revision"] == verified["application_revision"]
                )
                assert not (directory / "stack/release-maintenance.json").exists()
            assert list((directory / "backups/postgres").glob("*/*.dump"))
            publish.single(topic, "24.5", hostname="localhost", port=1884, qos=1)
            wait_for_measurement(client, entity, 24.5)
        finally:
            # Failed cutovers fence mutations. Preserve their original failure;
            # the Swarm fixture cleanup removes all resources after diagnostics.
            if not (directory / "stack/release-maintenance.json").exists():
                monitors = client.get(
                    "/v1/monitors/all", params={"include_docker_status": "false"}
                ).json()
                for worker in monitors:
                    if worker["container_name"] == worker_name:
                        client.delete(f"/v1/monitors/{worker['id']}").raise_for_status()
                remove_recorded_entity(client, entity)
