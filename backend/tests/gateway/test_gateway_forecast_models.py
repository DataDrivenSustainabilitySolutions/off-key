"""The gateway hands the composer's forecast model calls to TACTIC, never to the
forecast service."""

import pytest
from off_key_api_gateway.api.v1 import pipelines
from off_key_api_gateway.facades.tactic import TacticError
from off_key_core.auth.permissions import Permission
from off_key_core.models.adaptive import TIMESTRAL_CHECKPOINTS

from tests.support.gateway import gateway_app, member_profile
from tests.support.http import asgi_client

TOKEN = {"Authorization": "Bearer member-token"}
CHECKPOINT = TIMESTRAL_CHECKPOINTS[0]
MODEL = {
    "id": CHECKPOINT,
    "family": "timestral",
    "label": "Timestral 5M",
    "parameters": 5_000_000,
    "download_bytes": 21_000_000,
    "licence": "Modified MIT",
    "source": f"https://huggingface.co/{CHECKPOINT}",
    "revision": "a" * 40,
    "levels": [0.1, 0.5, 0.9],
    "max_context": 32_768,
    "max_horizon": 1_024,
    "status": "downloading",
    "progress": 0.4,
    "error": None,
}


@pytest.fixture
def calls(monkeypatch):
    recorded = []

    async def request(method, endpoint, **kwargs):
        recorded.append((method, endpoint, kwargs))
        if method == "POST":
            return MODEL
        return {"service": "available", "models": [MODEL]}

    monkeypatch.setattr(pipelines.tactic, "request", request)
    return recorded


@pytest.mark.asyncio
async def test_any_member_reads_the_models_through_tactic(calls):
    async with asgi_client(gateway_app(member_profile("user"))) as client:
        response = await client.get("/v1/forecast-models", headers=TOKEN)
    assert response.status_code == 200, response.text
    assert response.json() == {"service": "available", "models": [MODEL]}
    [(method, endpoint, kwargs)] = calls
    assert (method, endpoint) == (
        "GET",
        "/api/v1/monitors/pipelines/forecast-models",
    )
    assert kwargs["headers"] == TOKEN


@pytest.mark.asyncio
async def test_a_download_needs_manage_monitors_and_is_forwarded(calls):
    body = {"model": CHECKPOINT}
    async with asgi_client(gateway_app(member_profile("user"))) as client:
        refused = await client.post(
            "/v1/forecast-models/downloads", json=body, headers=TOKEN
        )
    assert refused.status_code == 403
    assert calls == []
    member = member_profile("user", permissions=[Permission.manage_monitors])
    async with asgi_client(gateway_app(member)) as client:
        accepted = await client.post(
            "/v1/forecast-models/downloads", json=body, headers=TOKEN
        )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["status"] == "downloading"
    [(method, endpoint, kwargs)] = calls
    assert (method, endpoint) == (
        "POST",
        "/api/v1/monitors/pipelines/forecast-models/downloads",
    )
    assert kwargs["json_data"] == body
    assert kwargs["headers"] == TOKEN


@pytest.mark.asyncio
async def test_tactics_reason_reaches_the_member(monkeypatch):
    async def request(method, endpoint, **kwargs):
        raise TacticError(
            "HTTP 409",
            status=409,
            body={"detail": "This deployment has no forecast service."},
        )

    monkeypatch.setattr(pipelines.tactic, "request", request)
    async with asgi_client(gateway_app(member_profile("admin"))) as client:
        response = await client.post(
            "/v1/forecast-models/downloads", json={"model": CHECKPOINT}, headers=TOKEN
        )
    assert response.status_code == 409
    assert response.json()["detail"] == "This deployment has no forecast service."
