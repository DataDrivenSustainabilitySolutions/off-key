"""The shared forecast service: providers, download states and its HTTP API."""

import threading
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from off_key_core.schemas.forecast import (
    MAX_CONTEXT_LENGTH,
    QUANTILE_LEVELS,
    ForecastRequest,
)
from off_key_forecast.api import create_app
from off_key_forecast.config.config import ForecastSettings
from off_key_forecast.main import require_writable_cache
from off_key_forecast.providers import naive_providers
from off_key_forecast.providers.base import ModelSpec
from off_key_forecast.providers.naive import SeasonalNaive
from off_key_forecast.registry import ModelNotReady, ModelRegistry
from pydantic import SecretStr, ValidationError


class GatedProvider:
    """Weights that arrive only when the test opens the gate."""

    def __init__(self, fail: bool = False) -> None:
        self.spec = ModelSpec(
            id="test/gated",
            family="test",
            label="Gated",
            licence="test",
            levels=QUANTILE_LEVELS,
            max_context=64,
            max_horizon=8,
            parameters=5_000_000,
            download_bytes=21_000_000,
            source="test/gated",
            revision="abc123",
        )
        self.gate = threading.Event()
        self.started = threading.Event()
        self.fail = fail
        self.loads = 0

    def is_downloaded(self, cache_dir: Path) -> bool:
        return (cache_dir / "gated.bin").exists()

    def download(self, cache_dir: Path, progress) -> None:
        self.started.set()
        progress(0.5)
        self.gate.wait(timeout=5)
        if self.fail:
            raise ConnectionError("hub unreachable")
        (cache_dir / "gated.bin").write_bytes(b"weights")

    def load(self, cache_dir: Path) -> SeasonalNaive:
        self.loads += 1
        return SeasonalNaive(1)


def _client(registry: ModelRegistry, token: str | None = None) -> TestClient:
    return TestClient(create_app(registry, SecretStr(token) if token else None))


def _naive_registry(tmp_path: Path) -> ModelRegistry:
    return ModelRegistry(naive_providers([1, 4]), tmp_path)


def test_seasonal_naive_repeats_the_season_and_widens_with_the_horizon():
    rng = np.random.default_rng(1)
    season = np.array([0.0, 10.0, 0.0, -10.0])
    values = np.tile(season, 50) + rng.normal(0, 1, 200)
    quantiles = SeasonalNaive(4).forecast([values], 8)[0]

    assert quantiles.shape == (8, len(QUANTILE_LEVELS))
    assert np.all(np.diff(quantiles, axis=-1) >= 0)
    median = quantiles[:, QUANTILE_LEVELS.index(0.5)]
    np.testing.assert_allclose(median, values[-4:][np.arange(8) % 4], atol=0.5)
    width = quantiles[:, -1] - quantiles[:, 0]
    assert np.all(width[4:] > width[:4])


def test_seasonal_naive_band_covers_a_random_walk_at_the_stated_rate():
    rng = np.random.default_rng(7)
    walk = np.cumsum(rng.normal(0, 1, 1600))
    origins = range(600, 1600)
    quantiles = SeasonalNaive(1).forecast([walk[:origin] for origin in origins], 1)
    low = quantiles[:, 0, QUANTILE_LEVELS.index(0.05)]
    high = quantiles[:, 0, QUANTILE_LEVELS.index(0.95)]
    truth = walk[600:1600]
    inside = np.mean((truth >= low) & (truth <= high))
    assert 0.86 <= inside <= 0.94


def test_seasonal_naive_fills_gaps_and_short_series():
    quantiles = SeasonalNaive(24).forecast(
        [np.array([np.nan, 3.0, np.nan, 5.0]), np.array([2.0])], 3
    )
    assert np.isfinite(quantiles).all()
    np.testing.assert_allclose(quantiles[1], 2.0)
    assert quantiles[0, 0, QUANTILE_LEVELS.index(0.5)] == pytest.approx(3.0)


def test_request_bounds_reject_oversized_and_empty_input():
    with pytest.raises(ValidationError):
        ForecastRequest(model="m", series=[[None, None]], horizon=1)
    with pytest.raises(ValidationError):
        ForecastRequest(model="m", series=[[1.0] * (MAX_CONTEXT_LENGTH + 1)], horizon=1)
    with pytest.raises(ValidationError):
        ForecastRequest(model="m", series=[[1.0]], horizon=1025)
    with pytest.raises(ValidationError):
        ForecastRequest(model="m", series=[[1.0]] * 65, horizon=1)


def test_api_lists_models_and_forecasts_a_batch(tmp_path):
    client = _client(_naive_registry(tmp_path))

    listed = client.get("/v1/models").json()["models"]
    assert [item["id"] for item in listed] == ["naive/season-1", "naive/season-4"]
    assert {item["status"] for item in listed} == {"ready"}

    response = client.post(
        "/v1/forecast",
        json={
            "model": "naive/season-4",
            "series": [[1, 2, 3, 4, 1, 2, 3, 4], [5, None, 7]],
            "horizon": 6,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["levels"] == list(QUANTILE_LEVELS)
    assert np.array(body["quantiles"]).shape == (2, 6, 21)
    assert body["quantiles"][0][0][10] == pytest.approx(1.0)


def test_api_rejects_unknown_models_and_horizons_past_the_model(tmp_path):
    (tmp_path / "gated.bin").write_bytes(b"weights")
    client = _client(ModelRegistry([GatedProvider()], tmp_path))

    assert (
        client.post(
            "/v1/forecast", json={"model": "nope", "series": [[1]], "horizon": 1}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/forecast", json={"model": "test/gated", "series": [[1]], "horizon": 9}
        ).status_code
        == 422
    )
    assert client.post("/v1/downloads", json={"model": "nope"}).status_code == 404


def test_first_forecast_starts_the_download_and_answers_once_ready(tmp_path):
    provider = GatedProvider()
    registry = ModelRegistry([provider], tmp_path)
    client = _client(registry)
    request = {"model": "test/gated", "series": [[1.0, 2.0, 3.0]], "horizon": 2}

    assert client.get("/v1/models").json()["models"][0]["status"] == "not_downloaded"
    waiting = client.post("/v1/forecast", json=request)
    assert waiting.status_code == 503
    assert waiting.headers["Retry-After"] == "10"
    assert waiting.json()["status"] == "downloading"
    assert provider.started.wait(timeout=5)
    assert client.get("/v1/models").json()["models"][0]["progress"] == 0.5

    # Asking again while it downloads queues nothing new.
    assert client.post("/v1/forecast", json=request).status_code == 503
    provider.gate.set()
    registry.wait_for_downloads()

    ready = client.post("/v1/forecast", json=request)
    assert ready.status_code == 200, ready.text
    assert ready.json()["revision"] == "abc123"
    client.post("/v1/forecast", json=request)
    assert provider.loads == 1


def test_a_failed_download_reports_its_error_and_can_be_retried(tmp_path):
    provider = GatedProvider(fail=True)
    registry = ModelRegistry([provider], tmp_path)
    client = _client(registry)

    assert (
        client.post("/v1/downloads", json={"model": "test/gated"}).json()["status"]
        == "downloading"
    )
    provider.gate.set()
    registry.wait_for_downloads()
    info = client.get("/v1/models").json()["models"][0]
    assert info["status"] == "failed"
    assert "hub unreachable" in info["error"]

    provider.fail = False
    retried = client.post("/v1/downloads", json={"model": "test/gated"})
    assert retried.status_code == 202
    registry.wait_for_downloads()
    assert registry.info("test/gated").status == "ready"


def test_weights_already_in_the_cache_are_ready_at_start(tmp_path):
    (tmp_path / "gated.bin").write_bytes(b"weights")
    registry = ModelRegistry([GatedProvider()], tmp_path)
    assert registry.info("test/gated").status == "ready"
    registry.get("test/gated")


def test_registry_raises_not_ready_with_the_status(tmp_path):
    provider = GatedProvider()
    registry = ModelRegistry([provider], tmp_path)
    with pytest.raises(ModelNotReady) as raised:
        registry.get("test/gated")
    assert raised.value.info.status == "downloading"
    provider.gate.set()
    registry.wait_for_downloads()


def test_token_guards_everything_but_liveness(tmp_path):
    client = _client(_naive_registry(tmp_path), token="secret")

    assert client.get("/health/live").status_code == 200
    assert client.get("/v1/models").status_code == 401
    assert (
        client.get("/v1/models", headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )
    assert (
        client.get("/v1/models", headers={"Authorization": "Bearer secret"}).status_code
        == 200
    )


def test_settings_parse_season_lengths_and_ignore_an_empty_token(monkeypatch):
    monkeypatch.setenv("FORECAST_API_TOKEN", "")
    monkeypatch.setenv("FORECAST_NAIVE_SEASON_LENGTHS", "1,48")
    config = ForecastSettings().config
    assert config.api_token is None
    assert config.naive_season_lengths == (1, 48)
    monkeypatch.setenv("FORECAST_NAIVE_SEASON_LENGTHS", "0")
    with pytest.raises(ValueError):
        _ = ForecastSettings().config


def test_a_deployment_hands_the_token_over_as_a_secret_file(tmp_path, monkeypatch):
    """Swarm mounts the token at /run/secrets/FORECAST_API_TOKEN, not in the env."""
    monkeypatch.delenv("FORECAST_API_TOKEN", raising=False)
    (tmp_path / "FORECAST_API_TOKEN").write_text("s" * 64 + "\n")

    config = ForecastSettings(_secrets_dir=tmp_path).config

    assert config.api_token.get_secret_value() == "s" * 64
    client = TestClient(create_app(_naive_registry(tmp_path), config.api_token))
    assert client.get("/v1/models").status_code == 401
    headers = {"Authorization": "Bearer " + "s" * 64}
    assert client.get("/v1/models", headers=headers).status_code == 200


def test_the_service_does_not_start_where_weights_cannot_be_kept(tmp_path):
    """A volume the service cannot write to fails the release, not a first download."""
    require_writable_cache(tmp_path / "models")
    assert list((tmp_path / "models").iterdir()) == []

    blocked = tmp_path / "not-a-directory"
    blocked.write_text("")
    with pytest.raises(SystemExit, match=r"FORECAST_CACHE_DIR .* is not writable"):
        require_writable_cache(blocked / "models")
