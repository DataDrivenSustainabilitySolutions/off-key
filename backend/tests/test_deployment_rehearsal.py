"""Keep real user/configuration/data/monitor state across a production redeploy.

The volume cutover runs the actual Ansible backup and TimescaleDB restore tasks.
The next identical deployment checks that retries do not duplicate workers.
"""

import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from paho.mqtt import publish

from .test_adaptive_lane_e2e import (
    _remove_catalog_charger,
    _wait_until_service_accepts_data,
)

pytestmark = pytest.mark.skipif(
    os.getenv("OFFKEY_DEPLOYMENT_REHEARSAL") != "1",
    reason="requires the disposable production Swarm rehearsal",
)


def wait_for_measurement(client, charger, value):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        response = client.get(
            f"/v1/telemetry/{charger}/data", params={"type": "temperature"}
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
    charger = str(uuid4())
    source_id = str(uuid4())
    topic = f"device/evCharger/{charger}/temperature"
    worker_name = "rehearsal-" + charger
    headers = {"Authorization": f"Bearer {os.environ['E2E_AUTH_TOKEN']}"}
    with httpx.Client(
        base_url="http://localhost:8000", headers=headers, timeout=210
    ) as client:
        member = client.get("/v1/members/me")
        member.raise_for_status()
        snapshot = client.get("/v1/sources").json()
        catalog = snapshot["catalog"]
        catalog["sources"].append(
            {
                "id": source_id,
                "label": "Rehearsal source",
                "host": "source-broker",
                "port": 1883,
                "verified": True,
                "chargers": [
                    {
                        "id": charger,
                        "local_id": charger,
                        "label": "Rehearsal charger",
                        "policy": {"mode": "original"},
                        "sensors": [
                            {
                                "key": "temperature",
                                "label": "Temperature",
                                "upstream_topic": topic,
                            }
                        ],
                    }
                ],
            }
        )
        response = client.put(
            "/v1/sources",
            json={"expected_revision": snapshot["revision"], "catalog": catalog},
        )
        response.raise_for_status()
        revision = response.json()["revision"]
        catalog = response.json()["catalog"]
        try:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                status = client.get("/v1/sources/status").json()
                if (
                    status["ingress"]
                    .get("sources", {})
                    .get(source_id, {})
                    .get("status")
                    == "connected"
                ):
                    break
                time.sleep(1)
            else:
                pytest.fail("Test source did not connect before the redeploy")
            publish.single(topic, "23.5", hostname="localhost", port=1884, qos=1)
            saved_data = wait_for_measurement(client, charger, 23.5)
            started = client.post(
                "/v1/monitors/start",
                json={
                    "container_name": worker_name,
                    "mqtt_topics": [topic],
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
                current = client.get("/v1/sources").json()
                assert current["revision"] == revision
                assert current["catalog"] == catalog
                assert (
                    client.get(
                        f"/v1/telemetry/{charger}/data", params={"type": "temperature"}
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
                _wait_until_service_accepts_data(client, workers[0]["id"])
                record = json.loads((directory / "stack/release.json").read_text())
                assert (
                    record["application_revision"] == verified["application_revision"]
                )
                assert not (directory / "stack/release-maintenance.json").exists()
            assert list((directory / "backups/postgres").glob("*/*.dump"))
            publish.single(topic, "24.5", hostname="localhost", port=1884, qos=1)
            wait_for_measurement(client, charger, 24.5)
        finally:
            monitors = client.get(
                "/v1/monitors/all", params={"include_docker_status": "false"}
            ).json()
            for worker in monitors:
                if worker["container_name"] == worker_name:
                    client.delete(f"/v1/monitors/{worker['id']}").raise_for_status()
            _remove_catalog_charger(client, source_id, charger)
