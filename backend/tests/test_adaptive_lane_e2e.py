"""Opt-in production-like adaptive lane test against the Docker stack."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_ADAPTIVE_E2E") != "1",
    reason="requires the Docker Gateway/TACTIC/RADAR/MQTT/PostgreSQL stack",
)


def _publish(topic: str, value: float, timestamp: datetime) -> None:
    payload = json.dumps({"timestamp": timestamp.isoformat(), "value": value})
    password = os.environ["EMQX_DASHBOARD_PASSWORD"]
    response = httpx.post(
        f"{os.getenv('EMQX_API_URL', 'http://localhost:18083')}/api/v5/publish",
        auth=(os.getenv("EMQX_DASHBOARD_USERNAME", "admin"), password),
        json={"topic": topic, "payload": payload, "qos": 0, "retain": False},
        timeout=10,
    )
    response.raise_for_status()


def test_gateway_to_postgres_adaptive_multisensor_input_correlation() -> None:
    token = os.environ["E2E_AUTH_TOKEN"]
    base_url = os.getenv("E2E_API_URL", "http://localhost:8000/api")
    charger_id = f"adaptive-e2e-{uuid.uuid4().hex[:8]}"
    topics = [
        f"charger/{charger_id}/live-telemetry/L1",
        f"charger/{charger_id}/live-telemetry/L2",
    ]
    service_id: str | None = None
    headers = {"Authorization": f"Bearer {token}"}

    with httpx.Client(base_url=base_url, headers=headers, timeout=210) as client:
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
            time.sleep(5)
            published_cycles: list[dict[str, str]] = []
            for index in range(8):
                l1_time = datetime.now(UTC)
                l2_time = l1_time + timedelta(milliseconds=50)
                _publish(topics[0], 100.0 if index == 7 else 1.0 + index / 100, l1_time)
                _publish(topics[1], 50.0 if index == 7 else 2.0 + index / 100, l2_time)
                published_cycles.append(
                    {"L1": l1_time.isoformat(), "L2": l2_time.isoformat()}
                )

            deadline = time.monotonic() + 120
            evidence: list[dict[str, object]] = []
            while time.monotonic() < deadline:
                evidence_response = client.get(
                    "/v1/monitors/evidence", params={"charger_id": charger_id}
                )
                evidence_response.raise_for_status()
                evidence = evidence_response.json()
                adaptive = [
                    row for row in evidence if row.get("strategy") == "adaptive_stream"
                ]
                if adaptive:
                    assert all(row["anomaly_score"] is not None for row in adaptive)
                    assert all(row["threshold"] is not None for row in adaptive)
                    assert all(row["p_value"] is None for row in adaptive)
                    for row in adaptive:
                        input_timestamps = row["input_timestamps"]
                        assert isinstance(input_timestamps, dict)
                        assert set(input_timestamps) == {"L1", "L2"}
                        assert input_timestamps in published_cycles
                        assert datetime.fromisoformat(str(row["timestamp"])) == max(
                            datetime.fromisoformat(value)
                            for value in input_timestamps.values()
                        )
                    break
                time.sleep(2)
            else:
                pytest.fail("No adaptive operational evidence reached PostgreSQL")
        finally:
            if service_id:
                client.delete(f"/v1/monitors/{service_id}")
