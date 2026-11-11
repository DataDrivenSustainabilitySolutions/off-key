"""The forecast service in process, for runs with a pretrained forecaster.

The Timestral checkpoints answer with the seasonal-naive baseline, so no
weights are downloaded: these tests check how RADAR uses the service, not what
the model forecasts.
"""

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient
from off_key_core.models.adaptive import TIMESTRAL_CHECKPOINTS
from off_key_forecast.api import create_app
from off_key_forecast.providers.naive import SeasonalNaiveProvider
from off_key_forecast.registry import ModelRegistry
from off_key_mqtt_radar.forecasting import ForecastClient, ForecastServiceError

_STATE: dict = {}


class StandInCheckpoint(SeasonalNaiveProvider):
    """A Timestral checkpoint's identity with the baseline's forecasts."""

    def __init__(self, checkpoint: str, season_length: int) -> None:
        super().__init__(season_length)
        self.spec = replace(
            self.spec, id=checkpoint, family="timestral", label=checkpoint
        )


def client() -> ForecastClient:
    """Module-level, as a checkpoint stores a forecaster's connection by name."""
    http: TestClient = _STATE["http"]

    def transport(method, url, body, headers):
        if _STATE.get("down"):
            raise ForecastServiceError("Forecast service is unreachable: refused")
        _STATE["calls"].append((method, url))
        response = http.request(method, url, content=body, headers=headers)
        return response.status_code, response.content

    return ForecastClient("http://forecast", transport=transport)


def start(
    monkeypatch,
    cache_dir: Path,
    season_length: int = 1,
    checkpoints: tuple[str, ...] = TIMESTRAL_CHECKPOINTS,
) -> dict:
    """Serve the Timestral checkpoints to every forecaster RADAR builds.

    Returns the service's state: its ``calls``, and ``down`` to take it away.
    """
    registry = ModelRegistry(
        [StandInCheckpoint(checkpoint, season_length) for checkpoint in checkpoints],
        cache_dir,
    )
    monkeypatch.setitem(_STATE, "http", TestClient(create_app(registry, None)))
    monkeypatch.setitem(_STATE, "calls", [])
    monkeypatch.setitem(_STATE, "down", False)
    monkeypatch.setitem(_STATE, "registry", registry)
    monkeypatch.setattr("off_key_mqtt_radar.forecasting.service_client", client)
    return _STATE
