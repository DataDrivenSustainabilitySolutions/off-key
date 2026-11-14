"""Opt-in production-like adaptive lane test against the Docker stack."""

import os
import time
from datetime import datetime

import httpx
import pytest
from paho.mqtt.client import CallbackAPIVersion, Client

from tests.support.deployment import wait_until_service_accepts_data
from tests.support.integration_catalogue import (
    add_recorded_entity,
    remove_recorded_entity,
)

pytestmark = [
    pytest.mark.deployment,
    pytest.mark.skipif(
        os.getenv("RUN_ADAPTIVE_E2E") != "1",
        reason="requires the Docker Gateway/TACTIC/RADAR/MQTT/PostgreSQL stack",
    ),
]


def _publication_snapshots(
    readings: dict[str, str],
    published_values: list[dict[str, float]],
    observations: dict[str, dict[float, datetime]],
) -> list[dict[str, datetime]]:
    # L1 arrives before L2: its update may use the preceding L2, then the
    # next arrival refreshes both. Only exact snapshots of this order count.
    snapshots = []
    latest_inputs = {}
    for values in published_values:
        for key, value in values.items():
            latest_inputs[readings[key]] = observations[key][value]
            if len(latest_inputs) == len(readings):
                snapshots.append(dict(latest_inputs))
    return snapshots


def test_gateway_to_postgres_adaptive_multisensor_input_correlation() -> None:
    gateway_url = os.getenv("E2E_GATEWAY_URL", "http://localhost:8000").rstrip("/")
    headers = {"Authorization": f"Bearer {os.environ['E2E_AUTH_TOKEN']}"}
    with httpx.Client(base_url=gateway_url, headers=headers, timeout=210) as client:
        openapi = client.get("/openapi.json")
        openapi.raise_for_status()
        assert "post" in openapi.json()["paths"]["/v1/monitors"]
        entity = add_recorded_entity(client, label="Adaptive test", keys=("L1", "L2"))
        monitor_id = None
        publisher = Client(
            CallbackAPIVersion.VERSION2, client_id=f"adaptive-e2e-{entity.device_id}"
        )
        try:
            response = client.post(
                "/v1/monitors",
                json={
                    "display_name": f"radar-{entity.device_id}",
                    "reading_ids": list(entity.reading_ids),
                    "monitoring": {
                        "strategy": "adaptive_stream",
                        "model_type": "aberrant_online_isolation_forest",
                        "model_params": {"num_trees": 4, "max_leaf_samples": 4},
                        "training_window_size": 4,
                        "calibration_window_size": 2,
                        "threshold_config": {
                            "mode": "calibrated_quantile",
                            "quantile": 1.0,
                        },
                    },
                },
            )
            response.raise_for_status()
            monitor_id = response.json()["monitor_id"]
            wait_until_service_accepts_data(
                client, monitor_id, activation_id=response.json()["activation_id"]
            )
            publisher.connect(
                os.getenv("E2E_SOURCE_MQTT_HOST", "localhost"),
                int(os.getenv("E2E_SOURCE_MQTT_PORT", "1884")),
            )
            publisher.loop_start()
            published_values = []
            for index in range(8):
                values = {
                    "L1": 100.0 if index == 7 else 1.0 + index / 100,
                    "L2": 50.0 if index == 7 else 2.0 + index / 100,
                }
                published_values.append(values)
                for key, value in values.items():
                    message = publisher.publish(entity.topics[key], str(value), qos=1)
                    message.wait_for_publish(timeout=5)
                    assert message.is_published()
                time.sleep(0.1)
            # Compare evidence with persisted observations from the real upstream
            # path, including each input's individual ingestion timestamp.
            observations = {}
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                for key, reading_id in entity.readings.items():
                    response = client.get(f"/v1/readings/{reading_id}/measurements")
                    response.raise_for_status()
                    observations[key] = {
                        row["value"]: datetime.fromisoformat(row["timestamp"])
                        for row in response.json()
                    }
                if all(
                    all(values[key] in observations[key] for values in published_values)
                    for key in entity.readings
                ):
                    break
                time.sleep(1)
            else:
                pytest.fail(
                    "The upstream multivariate observations did not reach history"
                )
            cycles = _publication_snapshots(
                entity.readings, published_values, observations
            )
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                response = client.get(
                    "/v1/evidence", params={"reading_id": entity.reading_ids[0]}
                )
                response.raise_for_status()
                evidence = [
                    row
                    for row in response.json()
                    if row.get("monitor_id") == monitor_id
                    and row.get("strategy") == "adaptive_stream"
                ]
                seen = []
                for row in evidence:
                    assert (
                        row["anomaly_score"] is not None
                        and row["threshold"] is not None
                    )
                    assert row["p_value"] is None
                    assert set(row["input_timestamps"]) == set(entity.reading_ids)
                    inputs = {
                        key: datetime.fromisoformat(value)
                        for key, value in row["input_timestamps"].items()
                    }
                    assert inputs in cycles
                    assert datetime.fromisoformat(row["timestamp"]) == max(
                        inputs.values()
                    )
                    seen.append(inputs)
                if cycles[-1] in seen:
                    break
                time.sleep(2)
            else:
                pytest.fail(
                    "Final adaptive input cycle did not reach PostgreSQL evidence"
                )
        finally:
            publisher.disconnect()
            publisher.loop_stop()
            if monitor_id:
                client.delete(f"/v1/monitors/{monitor_id}").raise_for_status()
            remove_recorded_entity(client, entity)
