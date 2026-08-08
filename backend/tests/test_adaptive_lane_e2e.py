"""Opt-in production-like adaptive lane test against the Docker stack."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from paho.mqtt import publish as mqtt_publish

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_ADAPTIVE_E2E") != "1",
    reason="requires the Docker Gateway/TACTIC/RADAR/MQTT/PostgreSQL stack",
)


def _mqtt_message(
    topic: str, value: float, timestamp: datetime
) -> tuple[str, str, int, bool]:
    payload = json.dumps({"timestamp": timestamp.isoformat(), "value": value})
    return topic, payload, 0, False


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
    token = os.environ["E2E_AUTH_TOKEN"]
    gateway_url = os.getenv("E2E_GATEWAY_URL", "http://localhost:8000").rstrip("/")
    charger_id = f"adaptive-e2e-{uuid.uuid4().hex[:8]}"
    topics = [
        f"charger/{charger_id}/live-telemetry/L1",
        f"charger/{charger_id}/live-telemetry/L2",
    ]
    service_id: str | None = None
    headers = {"Authorization": f"Bearer {token}"}

    with httpx.Client(base_url=gateway_url, headers=headers, timeout=210) as client:
        openapi_response = client.get("/openapi.json")
        openapi_response.raise_for_status()
        assert "/v1/monitors/start" in openapi_response.json().get("paths", {}), (
            f"Gateway at {gateway_url} does not expose /v1/monitors/start"
        )

        response = client.post(
            "/v1/monitors/start",
            json={
                "container_name": f"radar-{charger_id}",
                "service_type": "radar",
                "mqtt_topics": topics,
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
        try:
            _wait_until_service_accepts_data(client, service_id)
            cycle_start = datetime.now(UTC)
            published_cycles: list[dict[str, datetime]] = []
            messages: list[tuple[str, str, int, bool]] = []
            for index in range(8):
                l1_time = cycle_start + timedelta(milliseconds=index * 100)
                l2_time = l1_time + timedelta(milliseconds=50)
                messages.extend(
                    [
                        _mqtt_message(
                            topics[0],
                            100.0 if index == 7 else 1.0 + index / 100,
                            l1_time,
                        ),
                        _mqtt_message(
                            topics[1],
                            50.0 if index == 7 else 2.0 + index / 100,
                            l2_time,
                        ),
                    ]
                )
                published_cycles.append({"L1": l1_time, "L2": l2_time})
            last_published_cycle = published_cycles[-1]
            mqtt_publish.multiple(
                messages,
                hostname=os.getenv("E2E_MQTT_HOST", "localhost"),
                port=int(os.getenv("E2E_MQTT_PORT", "1883")),
                client_id=f"adaptive-e2e-{charger_id}",
            )

            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                evidence_response = client.get(
                    "/v1/monitors/evidence", params={"charger_id": charger_id}
                )
                evidence_response.raise_for_status()
                adaptive = [
                    row
                    for row in evidence_response.json()
                    if row.get("service_id") == service_id
                    and row.get("strategy") == "adaptive_stream"
                ]
                if adaptive:
                    assert all(row["anomaly_score"] is not None for row in adaptive)
                    assert all(row["threshold"] is not None for row in adaptive)
                    assert all(row["p_value"] is None for row in adaptive)
                    parsed_cycles: list[dict[str, datetime]] = []
                    for row in adaptive:
                        input_timestamps = row["input_timestamps"]
                        assert isinstance(input_timestamps, dict)
                        assert set(input_timestamps) == {"L1", "L2"}
                        parsed_inputs = {
                            key: datetime.fromisoformat(str(value))
                            for key, value in input_timestamps.items()
                        }
                        assert parsed_inputs in published_cycles
                        parsed_cycles.append(parsed_inputs)
                        assert datetime.fromisoformat(str(row["timestamp"])) == max(
                            parsed_inputs.values()
                        )
                    if last_published_cycle in parsed_cycles:
                        break
                time.sleep(2)
            else:
                pytest.fail(
                    "Final adaptive input cycle did not reach PostgreSQL evidence"
                )
        finally:
            if service_id:
                client.delete(f"/v1/monitors/{service_id}")
