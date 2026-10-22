"""Deployed-stack helpers for the rehearsal tests."""

import time

import httpx
import pytest


def wait_until_service_accepts_data(
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
