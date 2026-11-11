"""The deployed forecast service serves real Timestral weights to the platform.

Runs against the rehearsal's production Swarm, where the service has no stand-in:
it downloads the smallest checkpoint from the Hugging Face Hub at its pinned
commit and forecasts with it. A worker reaches the service by the address and the
secret token the release gave it, and a monitor with a Timestral step goes through
preflight, a RADAR worker and the evidence the charts read.
"""

import json
import os
import re
import subprocess
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from off_key_core.models.adaptive import TIMESTRAL, TIMESTRAL_CHECKPOINTS
from off_key_core.schemas.forecast import QUANTILE_LEVELS
from paho.mqtt.client import CallbackAPIVersion, Client

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

STACK = os.getenv("OFFKEY_REHEARSAL_STACK", "offkey-smoke")
CHECKPOINT = TIMESTRAL_CHECKPOINTS[0]
PROBE = Path(__file__).parents[1] / "support/forecast_probe.py"
PYTHON = ("/app/bin/python",)
COMMIT = re.compile(r"[0-9a-f]{40}")
# The reading repeats every four values, then breaks its cycle once.
PATTERN = (0.0, 10.0, 0.0, -10.0)
TRAINING, CALIBRATION, OPERATIONAL = 30, 20, 12
BREAK = 150.0


def worker_container() -> str:
    """A running Dojo worker: a stack service that calls the forecast service."""
    containers = subprocess.run(
        [
            "docker",
            "ps",
            "--quiet",
            "--filter",
            f"label=com.docker.swarm.service.name={STACK}_dojo-worker",
            "--filter",
            "status=running",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.split()
    assert containers, "The rehearsal runs no Dojo worker"
    return containers[0]


@pytest.fixture(scope="module")
def worker_view() -> dict:
    """The service as a worker sees it, once the checkpoint's weights are there."""
    result = subprocess.run(
        ["docker", "exec", "-i", worker_container(), *PYTHON, "-", CHECKPOINT],
        input=PROBE.read_text(),
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.splitlines()[-1])


def test_a_worker_reaches_the_service_with_the_token_the_release_gave_it(worker_view):
    assert worker_view["url"] == "http://forecast:8020"
    # The token is a Swarm secret of the worker, never in its environment.
    assert worker_view["token_is_a_mounted_secret"]
    assert not worker_view["token_in_environment"]
    assert worker_view["refused_without_token"]
    # Every checkpoint the composer offers, each pinned to a Hub commit.
    assert set(worker_view["offered"]) == set(TIMESTRAL_CHECKPOINTS)
    assert all(COMMIT.fullmatch(pin) for pin in worker_view["offered"].values())


def test_the_service_downloads_real_weights_and_forecasts_a_season(worker_view):
    model = worker_view["model"]
    assert model["status"] == "ready", model
    forecast = worker_view["forecast"]
    assert forecast["revision"] == worker_view["offered"][CHECKPOINT]
    assert tuple(forecast["levels"]) == QUANTILE_LEVELS
    assert forecast["steps"] == 24
    # The season swings by 3; the median follows it and the band holds it.
    assert forecast["mean_absolute_error"] < 0.3, forecast
    assert forecast["covered"] >= 22, forecast


def timestral_design(catalog: dict) -> dict:
    """The adaptive template with a Timestral step in place of its detector."""
    assert catalog["authoring_enabled"]
    assert TIMESTRAL in {component["id"] for component in catalog["components"]}
    definition = deepcopy(
        next(item for item in catalog["templates"] if item["id"] == "adaptive_stream")[
            "definition"
        ]
    )
    definition["input_slots"] = [{"id": "value", "label": "Value"}]
    detector = next(node for node in definition["nodes"] if node["kind"] == "detector")
    detector["component"] = TIMESTRAL
    detector["params"] = {
        "checkpoint": CHECKPOINT,
        "context_length": 32,
        "minimum_context": 16,
    }
    definition["settings"].update(
        training_window_size=TRAINING, calibration_window_size=CALIBRATION
    )
    return definition


def activate(client: httpx.Client, entity, name: str) -> dict:
    """Publish the design and start it; preflight runs before the worker."""
    catalog = client.get("/v1/pipeline-components")
    catalog.raise_for_status()
    created = client.post(
        "/v1/pipelines",
        json={"name": name, "definition": timestral_design(catalog.json())},
    )
    created.raise_for_status()
    design = created.json()
    published = client.post(
        f"/v1/pipelines/{design['id']}/revisions",
        json={"expected_version": design["version"]},
    )
    published.raise_for_status()
    activated = client.post(
        "/v1/pipeline-activations",
        json={
            "revision_id": published.json()["id"],
            "bindings": {"value": entity.reading_ids[0]},
            "display_name": name,
            "idempotency_key": "timestral-" + entity.device_id,
        },
    )
    activated.raise_for_status()
    identifier = activated.json()["id"]
    deadline = time.monotonic() + 240
    progress = None
    while time.monotonic() < deadline:
        response = client.get(f"/v1/pipeline-activations/{identifier}")
        response.raise_for_status()
        progress = response.json()
        if progress["phase"] == "succeeded":
            return progress
        # Preflight fails here, on the step, where no forecast service is named.
        assert progress["phase"] not in {"failed", "cancelled"}, progress
        time.sleep(1)
    pytest.fail(f"The Timestral monitor did not start: {progress}")


def send(entity, cycle, broken) -> None:
    publisher = Client(
        CallbackAPIVersion.VERSION2, client_id=f"timestral-{entity.device_id}"
    )
    publisher.connect(
        os.getenv("E2E_SOURCE_MQTT_HOST", "localhost"),
        int(os.getenv("E2E_SOURCE_MQTT_PORT", "1884")),
    )
    publisher.loop_start()

    def publish(value):
        message = publisher.publish(entity.topics["value"], str(value), qos=1)
        message.wait_for_publish(timeout=5)
        assert message.is_published()

    try:
        for value in cycle:
            publish(value)
            # Slower than a forecast, so each value is scored before the next.
            time.sleep(0.25)
        # The break's forecast was asked for with the value before it.
        time.sleep(2)
        publish(broken)
    finally:
        publisher.disconnect()
        publisher.loop_stop()


def recorded_time(
    client: httpx.Client, reading_id: str, value: float
) -> datetime | None:
    response = client.get(f"/v1/readings/{reading_id}/measurements")
    response.raise_for_status()
    return next(
        (
            datetime.fromisoformat(row["timestamp"])
            for row in response.json()
            if row["value"] == value
        ),
        None,
    )


def scored_at(row: dict, reading_id: str) -> datetime | None:
    measured = row["input_timestamps"].get(reading_id)
    return datetime.fromisoformat(measured) if measured else None


def test_a_timestral_monitor_scores_live_values_and_alarms_on_the_break(worker_view):
    assert worker_view["model"]["status"] == "ready", worker_view["model"]
    headers = {"Authorization": f"Bearer {os.environ['E2E_AUTH_TOKEN']}"}
    gateway = os.getenv("E2E_GATEWAY_URL", "http://localhost:8000").rstrip("/")
    with httpx.Client(base_url=gateway, headers=headers, timeout=210) as client:
        entity = add_recorded_entity(client, label="Timestral test", keys=("value",))
        reading_id = entity.reading_ids[0]
        monitor_id = None
        try:
            activation = activate(client, entity, "Timestral " + entity.device_id)
            monitor_id = activation["monitor_id"]
            wait_until_service_accepts_data(client, monitor_id)
            cycle = [
                100.0 + PATTERN[index % 4]
                for index in range(TRAINING + CALIBRATION + OPERATIONAL)
            ]
            send(entity, cycle, BREAK)

            deadline = time.monotonic() + 180
            alarm, usual, state = None, [], None
            while time.monotonic() < deadline and alarm is None:
                time.sleep(2)
                response = client.get(f"/v1/monitors/{monitor_id}/pipeline/state")
                state = response.json() if response.status_code == 200 else None
                assert not state or state.get("phase") != "failed", state
                broken_at = recorded_time(client, reading_id, BREAK)
                if broken_at is None:
                    continue
                response = client.get("/v1/evidence", params={"reading_id": reading_id})
                response.raise_for_status()
                rows = [
                    row for row in response.json() if row["monitor_id"] == monitor_id
                ]
                alarm = next(
                    (row for row in rows if scored_at(row, reading_id) == broken_at),
                    None,
                )
                usual = [
                    row["anomaly_score"]
                    for row in rows
                    if row is not alarm and row["anomaly_score"] is not None
                ]
            assert alarm is not None, f"The break was never scored: {state}"

            # The forecast service answered the worker: the cycle is forecast
            # closely, so only the value that breaks it stands out.
            assert alarm["alarm"], alarm
            assert usual, "No value of the cycle was scored before the break"
            assert alarm["anomaly_score"] > 10 * max(usual) + 1, (alarm, max(usual))
        finally:
            if monitor_id:
                client.delete(f"/v1/monitors/{monitor_id}").raise_for_status()
            remove_recorded_entity(client, entity)
