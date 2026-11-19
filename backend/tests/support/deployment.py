"""Deployed-stack helpers for the rehearsal tests."""

import time
from copy import deepcopy

import httpx
import pytest


def wait_for_activation(
    client: httpx.Client, activation_id: str, deadline: float
) -> None:
    """Wait until an accepted start has created its worker."""
    phase = None
    while time.monotonic() < deadline:
        response = client.get(f"/v1/pipeline-activations/{activation_id}")
        response.raise_for_status()
        activation = response.json()
        phase = activation["phase"]
        if phase in {"awaiting_heartbeat", "succeeded"}:
            return
        if phase in {"failed", "cancelled"}:
            pytest.fail(f"Monitor start {phase}: {activation.get('error')}")
        time.sleep(1)
    pytest.fail(f"Monitor start did not create its worker; last phase: {phase}")


def wait_until_service_accepts_data(
    client: httpx.Client,
    monitor_id: str,
    timeout: float = 120,
    *,
    activation_id: str | None = None,
) -> None:
    deadline = time.monotonic() + timeout
    if activation_id is not None:
        # Form starts return before the worker exists; until then it reads as stopped.
        wait_for_activation(client, activation_id, deadline)
    last_status: object = None
    while time.monotonic() < deadline:
        response = client.get("/v1/monitors", params={"active": "true"})
        response.raise_for_status()
        service = next(
            (item for item in response.json() if item.get("id") == monitor_id), None
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


def bare_template(catalog: dict, strategy: str = "adaptive_stream") -> dict:
    """A bundled template from the served catalog without its example steps.

    The stream's template carries a Lags step as an example; these tests build
    on source, detector, policy and output, with the source wired to the detector.
    """
    definition = deepcopy(
        next(item for item in catalog["templates"] if item["id"] == strategy)[
            "definition"
        ]
    )
    steps = {node["id"] for node in definition["nodes"] if node["kind"] == "transform"}
    definition["nodes"] = [
        node for node in definition["nodes"] if node["id"] not in steps
    ]
    detector = next(
        node["id"] for node in definition["nodes"] if node["kind"] == "detector"
    )
    definition["edges"] = [
        {**edge, "target": detector} if edge["source"] == "input" else edge
        for edge in definition["edges"]
        if edge["source"] not in steps
    ]
    return definition
