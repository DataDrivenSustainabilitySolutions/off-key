"""TACTIC tells the composer what the forecast service holds and starts downloads."""

import threading
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from off_key_core.auth.permissions import ADMIN_ROLE, MEMBER_ROLE
from off_key_core.db.models import User
from off_key_core.models.adaptive import TIMESTRAL_CHECKPOINTS
from off_key_core.utils import forecast_client
from off_key_core.utils.forecast_client import ForecastServiceError
from off_key_forecast.api import create_app
from off_key_forecast.registry import ModelRegistry
from off_key_tactic_middleware.api.collection_auth import current_caller
from off_key_tactic_middleware.api.v1.pipelines import router
from off_key_tactic_middleware.domain import ConflictError, NotFoundError
from off_key_tactic_middleware.services.pipelines import forecast_models
from pydantic import SecretStr

from tests.support.forecast_service import StandInCheckpoint

TOKEN = "forecast-token-" + "t" * 32
SMALL, LARGE = TIMESTRAL_CHECKPOINTS[:2]
MODELS = "/monitors/pipelines/forecast-models"


class Downloadable(StandInCheckpoint):
    """A checkpoint whose weights arrive only when the test opens the gate."""

    def __init__(self, checkpoint: str, fail: bool = False) -> None:
        super().__init__(checkpoint, 1)
        self.spec = replace(self.spec, download_bytes=111_000_000)
        self.gate = threading.Event()
        self.fail = fail

    def is_downloaded(self, cache_dir: Path) -> bool:
        return (cache_dir / "weights.bin").exists()

    def download(self, cache_dir: Path, progress) -> None:
        progress(0.25)
        self.gate.wait(timeout=5)
        if self.fail:
            raise ConnectionError("no route to the Hub")
        (cache_dir / "weights.bin").write_bytes(b"weights")


@pytest.fixture
def service(monkeypatch, tmp_path):
    """A forecast service that asks for its token, where TACTIC is told to find it."""
    large = Downloadable(LARGE)
    registry = ModelRegistry([StandInCheckpoint(SMALL, 1), large], tmp_path)
    http = TestClient(create_app(registry, SecretStr(TOKEN)))
    state = {"down": False, "timeouts": [], "large": large, "registry": registry}

    def transport(timeout):
        state["timeouts"].append(timeout)

        def send(method, url, body, headers):
            if state["down"]:
                raise ForecastServiceError("Forecast service is unreachable: refused")
            response = http.request(method, url, content=body, headers=headers)
            return response.status_code, response.content

        return send

    monkeypatch.setattr(forecast_client, "_urllib_transport", transport)
    monkeypatch.setenv("TACTIC_FORECAST_API_URL", "http://forecast:8020")
    monkeypatch.setenv("FORECAST_API_TOKEN", TOKEN)
    yield state
    large.gate.set()
    registry.wait_for_downloads()
    registry.close()


def api(role=ADMIN_ROLE) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_caller] = lambda: User(
        id=1, email="member@example.com", role=role
    )
    return TestClient(app)


def test_a_deployment_without_the_service_says_so_and_downloads_nothing(monkeypatch):
    monkeypatch.delenv("TACTIC_FORECAST_API_URL", raising=False)
    catalog = forecast_models.forecast_models()
    assert (catalog.service, catalog.models) == ("not_deployed", [])
    with pytest.raises(ConflictError, match="no forecast service"):
        forecast_models.request_download(SMALL)
    assert api().get(MODELS).json() == {"service": "not_deployed", "models": []}
    refused = api().post(f"{MODELS}/downloads", json={"model": SMALL})
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "This deployment has no forecast service.",
    )


def test_every_checkpoint_is_listed_with_its_state_using_the_mounted_token(service):
    listed = api(MEMBER_ROLE).get(MODELS)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["service"] == "available"
    assert [(model["id"], model["status"]) for model in body["models"]] == [
        (SMALL, "ready"),
        (LARGE, "not_downloaded"),
    ]
    assert body["models"][1]["download_bytes"] == 111_000_000
    # A member waits for this answer, so it does not wait out a worker's timeout.
    assert set(service["timeouts"]) == {forecast_models.TIMEOUT_SECONDS}


def test_a_wrong_token_or_a_silent_service_reads_as_unreachable(service, monkeypatch):
    monkeypatch.setenv("FORECAST_API_TOKEN", "another-token-" + "x" * 32)
    assert forecast_models.forecast_models().service == "unreachable"
    monkeypatch.setenv("FORECAST_API_TOKEN", TOKEN)
    service["down"] = True
    assert api().get(MODELS).json() == {"service": "unreachable", "models": []}
    refused = api().post(f"{MODELS}/downloads", json={"model": LARGE})
    assert refused.status_code == 503
    assert "does not answer" in refused.json()["detail"]


def test_a_download_is_started_once_and_its_progress_and_end_are_listed(service):
    started = api().post(f"{MODELS}/downloads", json={"model": LARGE})
    assert started.status_code == 202, started.text
    assert started.json()["status"] == "downloading"
    # Asking again while it runs leaves the download as it is.
    assert forecast_models.request_download(LARGE).status == "downloading"
    downloading = forecast_models.forecast_models().models[1]
    assert (downloading.status, downloading.progress) == ("downloading", 0.25)
    service["large"].gate.set()
    service["registry"].wait_for_downloads()
    assert forecast_models.forecast_models().models[1].status == "ready"


def test_a_failed_download_gives_its_reason_and_can_be_asked_for_again(service):
    service["large"].fail = True
    service["large"].gate.set()
    forecast_models.request_download(LARGE)
    service["registry"].wait_for_downloads()
    failed = forecast_models.forecast_models().models[1]
    assert failed.status == "failed"
    assert failed.error == "ConnectionError: no route to the Hub"
    service["large"].fail = False
    assert forecast_models.request_download(LARGE).status == "downloading"
    service["registry"].wait_for_downloads()
    assert forecast_models.forecast_models().models[1].status == "ready"


def test_downloads_need_manage_monitors_and_a_model_the_service_offers(service):
    refused = api(MEMBER_ROLE).post(f"{MODELS}/downloads", json={"model": LARGE})
    assert refused.status_code == 403
    assert forecast_models.forecast_models().models[1].status == "not_downloaded"
    with pytest.raises(NotFoundError, match="does not offer mistralai/Unknown"):
        forecast_models.request_download("mistralai/Unknown")
    unknown = api().post(f"{MODELS}/downloads", json={"model": "mistralai/Unknown"})
    assert unknown.status_code == 404
    assert api().post(f"{MODELS}/downloads", json={}).status_code == 422
