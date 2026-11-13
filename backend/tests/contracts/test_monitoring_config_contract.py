"""Public validation and serialization of the shared RADAR launch contract."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from off_key_api_gateway.providers import get_form_monitor_starter
from off_key_core.schemas.radar import MonitorSetup
from off_key_mqtt_radar.config.config import RadarSettings
from off_key_tactic_middleware.config.config import (
    RadarRuntimeSettings,
    TacticSettings,
)
from off_key_tactic_middleware.services.orchestration import radar_environment

from tests.support.form_pipeline import form_launch
from tests.support.gateway import gateway_app, member, returning
from tests.support.http import asgi_client


def api(launch):
    return gateway_app(
        member("admin"), overrides={get_form_monitor_starter: returning(launch)}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_config",
    [
        {"monitoring": []},
        {"monitoring": {"strategy": "unsupported"}},
        {"monitoring": {"model_type": "pyod_iforest"}},
        {"monitoring": {"strategy": "static_baseline", "model_type": 123}},
        {"monitoring": {"strategy": "static_baseline", "model_type": "custom_model"}},
        {"monitoring": {"strategy": "static_baseline", "model_params": []}},
        {
            "monitoring": {
                "strategy": "static_baseline",
                "model_params": {"n_estimators": "invalid"},
            }
        },
        # The setup names readings; topics and the form's strategy fields are gone.
        {"strategy": "static_baseline"},
        {"model_type": "pyod_iforest"},
        {"static_baseline_config": {}},
        {"mqtt_topics": ["telemetry/c1/L1"]},
        {"performance_config": {"sensor_key_strategy": "leaf"}},
        {"reading_ids": []},
        {"reading_ids": ["L1", "L1"]},
        {"reading_ids": ["L 1"]},
        {"display_name": " "},
    ],
)
async def test_invalid_start_returns_422_without_launching(invalid_config):
    launch = AsyncMock()
    async with asgi_client(api(launch)) as client:
        response = await client.post(
            "/v1/monitors",
            json={"display_name": "radar-test", "reading_ids": ["L1"]} | invalid_config,
        )

    assert response.status_code == 422, response.text
    launch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "monitoring",
    [
        {
            "strategy": "static_baseline",
            "model_params": {"n_estimators": 5, "random_state": None},
            "training_window_size": 100,
            "calibration_window_size": 20,
            "seed": None,
        },
        {
            "strategy": "adaptive_stream",
            "model_params": {"num_trees": 2},
            "preprocessing_steps": [{"type": "standard_scaler"}],
            "threshold_config": {"quantile": 0.95},
        },
    ],
)
async def test_api_to_runtime_preserves_one_monitoring_config(monitoring, monkeypatch):
    launch = AsyncMock(
        return_value=SimpleNamespace(id="a1", service_id="m1", phase="requested")
    )
    async with asgi_client(api(launch)) as client:
        response = await client.post(
            "/v1/monitors",
            json={
                "display_name": "radar-test",
                "reading_ids": ["reading-l1", "reading-l2"],
                "monitoring": monitoring,
                "performance_config": {
                    "hold_intervals": 4.0,
                    "minimum_hold_seconds": 12.0,
                },
            },
        )
    assert response.status_code == 202, response.text
    [setup] = launch.await_args.args
    assert isinstance(setup, MonitorSetup)
    # The starter resolves the readings to their recorded topics and binds the
    # form's equivalent pipeline.
    config = setup.form(["telemetry/c1/L1", "telemetry/c1/L2"])
    launch = form_launch(**config.model_dump(mode="json"))
    monkeypatch.setattr(
        radar_environment, "get_tactic_settings", lambda: TacticSettings(_env_file=None)
    )
    monkeypatch.setattr(
        radar_environment,
        "get_radar_runtime_settings",
        lambda: RadarRuntimeSettings(
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
    assert runtime.sensor_key_strategy == "full_hierarchy"
    assert runtime.timing() == config.performance_config.timing()
    assert (runtime.hold_intervals, runtime.minimum_hold_seconds) == (4.0, 12.0)
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
