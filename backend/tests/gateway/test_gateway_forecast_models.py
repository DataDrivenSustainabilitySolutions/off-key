"""The composer's forecast model calls: who may read and who may download."""

import pytest
from off_key_api_gateway.api.v1 import pipelines
from off_key_core.auth.permissions import Permission
from off_key_core.models.adaptive import TIMESTRAL_CHECKPOINTS
from off_key_tactic_middleware.domain import ConflictError

from tests.support.gateway import gateway_app, member
from tests.support.http import asgi_client

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
    """What the forecast service was asked."""
    recorded = []

    def catalog():
        recorded.append(("list",))
        return {"service": "available", "models": [MODEL]}

    def download(model):
        recorded.append(("download", model))
        return MODEL

    monkeypatch.setattr(pipelines.forecast_models, "forecast_models", catalog)
    monkeypatch.setattr(pipelines.forecast_models, "request_download", download)
    return recorded


@pytest.mark.asyncio
async def test_any_member_reads_the_models(calls):
    async with asgi_client(gateway_app(member("user"))) as client:
        response = await client.get("/v1/forecast-models")
    assert response.status_code == 200, response.text
    assert response.json() == {"service": "available", "models": [MODEL]}
    assert calls == [("list",)]


@pytest.mark.asyncio
async def test_a_download_needs_manage_monitors(calls):
    body = {"model": CHECKPOINT}
    async with asgi_client(gateway_app(member("user"))) as client:
        refused = await client.post("/v1/forecast-models/downloads", json=body)
    assert refused.status_code == 403
    assert calls == []
    designer = member("designer", permissions=[Permission.manage_monitors])
    async with asgi_client(gateway_app(designer)) as client:
        accepted = await client.post("/v1/forecast-models/downloads", json=body)
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["status"] == "downloading"
    assert calls == [("download", CHECKPOINT)]


@pytest.mark.asyncio
async def test_the_reason_a_download_is_refused_reaches_the_member(monkeypatch):
    def download(model):
        raise ConflictError("This deployment has no forecast service.")

    monkeypatch.setattr(pipelines.forecast_models, "request_download", download)
    async with asgi_client(gateway_app(member("admin"))) as client:
        response = await client.post(
            "/v1/forecast-models/downloads", json={"model": CHECKPOINT}
        )
    assert response.status_code == 409
    assert response.json()["detail"] == "This deployment has no forecast service."
