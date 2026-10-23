"""Public validation and serialization of the shared RADAR launch contract."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from off_key_api_gateway.api.v1 import monitors
from off_key_api_gateway.facades.tactic import Tactic
from off_key_mqtt_radar.config.config import RadarSettings
from off_key_tactic_middleware.api.v1 import radar
from off_key_tactic_middleware.config.config import (
    RadarContainerRuntimeSettings,
    TacticSettings,
)
from off_key_tactic_middleware.services.orchestration import radar_environment

from tests.support.form_pipeline import form_launch


@pytest.mark.parametrize("boundary", ["gateway", "tactic"])
@pytest.mark.parametrize(
    "invalid_config",
    [
        {"strategy": []},
        {"model_type": 123},
        {"model_params": []},
        {"static_baseline_config": []},
        {"model_type": "custom_model"},
        {"adaptive_stream_config": {}},
        {
            "model_type": "pyod_knn",
            "static_baseline_config": {"model_type": "pyod_iforest"},
        },
        {
            "model_params": {"n_estimators": 5},
            "static_baseline_config": {"model_params": {"n_estimators": 10}},
        },
        {"model_params": {"n_estimators": "invalid"}},
        {"monitoring": {"strategy": "unsupported"}},
        {"monitoring": {"strategy": "static_baseline"}, "model_type": None},
        {"mqtt_topics": ["telemetry/ /L1"]},
    ],
)
def test_invalid_start_returns_422_without_launching(
    boundary, invalid_config, monkeypatch
):
    app = FastAPI()
    launch = AsyncMock()
    if boundary == "gateway":
        app.include_router(monitors.router, prefix="/v1/monitors")
        monkeypatch.setattr(monitors.tactic, "start_radar_service", launch)
        path = "/v1/monitors/start"
    else:
        app.include_router(radar.router, prefix="/api/v1/orchestration")
        app.dependency_overrides[radar.get_form_monitor_starter] = lambda: launch
        path = "/api/v1/orchestration/radar/services/start/"

    with TestClient(app) as client:
        response = client.post(
            path,
            json={
                "container_name": "radar-test",
                "mqtt_topics": ["telemetry/c1/L1"],
                **invalid_config,
            },
        )

    assert response.status_code == 422, response.text
    launch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "legacy_config",
    [
        {
            "static_baseline_config": {
                "model_params": {"n_estimators": 5, "random_state": None},
                "training_window_size": 100,
                "calibration_window_size": 20,
                "seed": None,
            },
        },
        {
            "strategy": "adaptive_stream",
            "adaptive_stream_config": {
                "model_params": {"num_trees": 2},
                "preprocessing_steps": [{"type": "standard_scaler"}],
                "threshold_config": {"quantile": 0.95},
            },
        },
    ],
)
async def test_gateway_to_runtime_preserves_one_monitoring_config(
    legacy_config, monkeypatch
):
    config = monitors.MonitoringServiceConfig(
        container_name="radar-test",
        mqtt_topics=["telemetry/c1/L1", "telemetry/c1/L2"],
        performance_config={
            "sensor_key_strategy": "leaf",
            "sensor_freshness_seconds": 12.0,
        },
        **legacy_config,
    )
    facade = object.__new__(Tactic)
    facade.request = AsyncMock()
    await facade.start_radar_service(config)
    payload = facade.request.await_args.kwargs["json_data"]
    assert set(payload) == {
        "launch_version",
        "container_name",
        "mqtt_topics",
        "monitoring",
        "performance_config",
    }
    assert payload["launch_version"] == 1
    # TACTIC binds the form's readings into the equivalent pipeline.
    launch = form_launch(**payload)

    monkeypatch.setattr(
        radar_environment, "get_tactic_settings", lambda: TacticSettings(_env_file=None)
    )
    monkeypatch.setattr(
        radar_environment,
        "get_radar_container_runtime_settings",
        lambda: RadarContainerRuntimeSettings(
            _env_file=None,
            ENVIRONMENT="development",
            POSTGRES_USER="test",
            POSTGRES_PASSWORD="test",
            POSTGRES_HOST="localhost",
            POSTGRES_PORT=5432,
            POSTGRES_DB="radar",
            RADAR_CHECKPOINT_SECRET="monitoring-contract-test-key",
        ),
    )
    environment = radar_environment.build_radar_environment(
        service_id="test-service", config=launch, validate_params=False
    )
    for name in RadarSettings.model_fields:
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    runtime = RadarSettings(_env_file=None).config

    assert runtime.monitoring == launch.monitoring
    assert runtime.monitoring.strategy == config.monitoring.strategy
    assert runtime.monitoring.model_params == (
        launch.monitoring.model_params | config.monitoring.model_params
    )
    assert runtime.subscription_topics == config.mqtt_topics
    assert runtime.sensor_key_strategy == config.performance_config.sensor_key_strategy
    assert (
        runtime.sensor_freshness_seconds
        == config.performance_config.sensor_freshness_seconds
    )
    assert (
        not {
            "RADAR_MONITORING_STRATEGY",
            "RADAR_MODEL_TYPE",
            "RADAR_MODEL_PARAMS",
            "RADAR_STATIC_BASELINE_CONFIG",
            "RADAR_ADAPTIVE_STREAM_CONFIG",
        }
        & environment.keys()
    )
