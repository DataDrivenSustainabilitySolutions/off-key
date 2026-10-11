"""Opt-in production-like adaptive lane test against the Docker stack."""

import os
import time
from datetime import datetime

import httpx
import pytest
from paho.mqtt.client import CallbackAPIVersion, Client

from .integration_catalogue import add_recorded_entity, remove_recorded_entity

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_ADAPTIVE_E2E") != "1",
    reason="requires the Docker Gateway/TACTIC/RADAR/MQTT/PostgreSQL stack",
)


def _wait_until_service_accepts_data(
    client: httpx.Client, service_id: str, timeout: float = 120
) -> None:
    deadline = time.monotonic() + timeout
    last_status: object = None
    while time.monotonic() < deadline:
        response = client.get(
            "/v1/monitors/all",
            params={"active_only": "true", "include_docker_status": "true"},
        )
        response.raise_for_status()
        service = next(
            (item for item in response.json() if item.get("id") == service_id), None
        )
        last_status = service.get("operational_status") if service else None
        if isinstance(last_status, dict):
            stage = last_status.get("stage")
            if stage == "waiting_for_data":
                return
            if stage in {"failed", "stopped"}:
                pytest.fail(
                    f"Adaptive service entered terminal stage {stage!r}: {last_status}"
                )
        time.sleep(1)
    pytest.fail(
        f"Adaptive service did not become ready within {timeout:g} seconds; "
        f"last status: {last_status}"
    )


def test_gateway_to_postgres_adaptive_multisensor_input_correlation() -> None:
    gateway_url = os.getenv("E2E_GATEWAY_URL", "http://localhost:8000").rstrip("/")
    headers = {"Authorization": f"Bearer {os.environ['E2E_AUTH_TOKEN']}"}
    with httpx.Client(base_url=gateway_url, headers=headers, timeout=210) as client:
        openapi = client.get("/openapi.json")
        openapi.raise_for_status()
        assert "/v1/monitors/start" in openapi.json()["paths"]
        entity = add_recorded_entity(client, label="Adaptive test", keys=("L1", "L2"))
        service_id = None
        publisher = Client(
            CallbackAPIVersion.VERSION2, client_id=f"adaptive-e2e-{entity.device_id}"
        )
        try:
            response = client.post(
                "/v1/monitors/start",
                json={
                    "container_name": f"radar-{entity.device_id}",
                    "service_type": "radar",
                    "mqtt_topics": list(entity.accepted_topics),
                    "strategy": "adaptive_stream",
                    "model_type": "aberrant_online_isolation_forest",
                    "model_params": {"num_trees": 4, "max_leaf_samples": 4},
                    "adaptive_stream_config": {
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
            service_id = response.json()["service_id"]
            _wait_until_service_accepts_data(client, service_id)
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
                for key, telemetry_key in entity.keys.items():
                    response = client.get(
                        f"/v1/telemetry/{entity.entity_id}/data",
                        params={"type": telemetry_key},
                    )
                    response.raise_for_status()
                    observations[key] = {
                        row["value"]: datetime.fromisoformat(row["timestamp"])
                        for row in response.json()
                    }
                if all(
                    all(values[key] in observations[key] for values in published_values)
                    for key in entity.keys
                ):
                    break
                time.sleep(1)
            else:
                pytest.fail(
                    "The upstream multivariate observations did not reach history"
                )
            cycles = [
                {
                    entity.keys[key]: observations[key][value]
                    for key, value in values.items()
                }
                for values in published_values
            ]
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                response = client.get(
                    "/v1/monitors/evidence", params={"charger_id": entity.entity_id}
                )
                response.raise_for_status()
                evidence = [
                    row
                    for row in response.json()
                    if row.get("service_id") == service_id
                    and row.get("strategy") == "adaptive_stream"
                ]
                seen = []
                for row in evidence:
                    assert (
                        row["anomaly_score"] is not None
                        and row["threshold"] is not None
                    )
                    assert row["p_value"] is None
                    assert set(row["input_timestamps"]) == set(entity.keys.values())
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
            if service_id:
                client.delete(f"/v1/monitors/{service_id}").raise_for_status()
            remove_recorded_entity(client, entity)
