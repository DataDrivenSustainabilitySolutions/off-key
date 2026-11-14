"""Integration-style tests for the static monitoring start contract."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from off_key_api_gateway.providers import get_form_monitor_starter
from off_key_core.schemas.radar import MonitorSetup
from off_key_core.schemas.radar import (
    PerformanceConfig as GatewayPerformanceConfig,
)
from off_key_tactic_middleware.config.config import TacticSettings
from off_key_tactic_middleware.services.orchestration.radar_environment import (
    build_radar_environment,
)
from off_key_tactic_middleware.services.orchestration.radar_status import (
    derive_operational_status,
)
from pydantic import ValidationError

from tests.support.env import DATABASE_ENVIRONMENT, set_environment
from tests.support.form_pipeline import form_launch
from tests.support.gateway import gateway_app, member, returning
from tests.support.http import asgi_client


@pytest.mark.asyncio
async def test_starting_a_monitor_hands_on_its_performance_config():
    setup = MonitorSetup(
        display_name="radar-charger-1",
        reading_ids=["sine", "cosine"],
        monitoring={
            "strategy": "static_baseline",
            "model_type": "pyod_iforest",
            "model_params": {"n_estimators": 128},
        },
        performance_config={
            "hold_intervals": 4.0,
            "minimum_hold_seconds": 45.0,
            "future_tolerance_seconds": 2.0,
        },
    )
    mock_start = AsyncMock(
        return_value=SimpleNamespace(
            id="activation-1", service_id="svc-1", phase="requested"
        )
    )
    app = gateway_app(
        member("admin"), overrides={get_form_monitor_starter: returning(mock_start)}
    )
    async with asgi_client(app) as client:
        response = await client.post(
            "/v1/monitors", json=setup.model_dump(mode="json", exclude_unset=True)
        )

    assert response.status_code == 202, response.text
    assert response.json() == {
        "monitor_id": "svc-1",
        "activation_id": "activation-1",
        "phase": "requested",
        "reading_ids": ["sine", "cosine"],
    }
    forwarded = mock_start.await_args.args[0].model_dump()
    assert forwarded["reading_ids"] == ["sine", "cosine"]
    assert forwarded["monitoring"]["strategy"] == "static_baseline"
    assert forwarded["performance_config"] == {
        "hold_intervals": 4.0,
        "minimum_hold_seconds": 45.0,
        "future_tolerance_seconds": 2.0,
    }
    assert forwarded["monitoring"]["martingale_config"] == {
        "trackers": [
            {
                "tracker_id": "primary",
                "betting_function": "power",
                "alarm_statistic": "restarted_martingale",
                "epsilon": 0.5,
                "threshold_config": {"mode": "manual", "value": 100.0},
            }
        ],
        "automatic_threshold_calibration": {
            "false_alarm_probability": 0.01,
            "horizon": 1000,
            "simulation_count": 5000,
        },
    }
    # The form TACTIC derives keeps the display name and full feature names.
    form = setup.form(["telemetry/charger-1/sine", "telemetry/charger-1/cosine"])
    assert form.container_name == form.display_name == "radar-charger-1"
    assert form.performance_config.sensor_key_strategy == "full_hierarchy"
    assert form.performance_config.hold_intervals == 4.0


@pytest.mark.parametrize(
    "change",
    [
        {"reading_ids": []},
        {"reading_ids": ["L1", "L1"]},
        {"reading_ids": ["L 1"]},
        {"mqtt_topics": ["telemetry/c1/L1"]},
        {"performance_config": {"sensor_key_strategy": "leaf"}},
        {"strategy": "adaptive_stream"},
    ],
)
def test_gateway_monitor_setup_names_readings_only(change):
    with pytest.raises(ValidationError):
        MonitorSetup(**{"display_name": "radar", "reading_ids": ["L1"]} | change)


def test_gateway_accepts_adaptive_strategy():
    config = MonitorSetup(
        display_name="radar",
        reading_ids=["L1"],
        monitoring={"strategy": "adaptive_stream", "training_window_size": 1200},
    )
    assert config.monitoring.strategy == "adaptive_stream"
    assert config.monitoring.training_window_size == 1200


def test_setup_rejects_incompatible_adaptive_feature_count():
    setup = MonitorSetup(
        display_name="radar",
        reading_ids=["L1", "L2"],
        monitoring={
            "strategy": "adaptive_stream",
            "model_type": "aberrant_moving_average",
        },
    )
    with pytest.raises(ValueError, match="exactly one feature"):
        setup.form(["telemetry/c1/L1", "telemetry/c1/L2"])
    with pytest.raises(ValidationError, match="alignment_mode"):
        GatewayPerformanceConfig(alignment_mode="strict_barrier")


def test_gateway_resolves_strategy_specific_default_model():
    config = MonitorSetup(
        display_name="radar",
        reading_ids=["L1"],
        monitoring={"strategy": "adaptive_stream"},
    )
    assert config.monitoring.model_type == "aberrant_online_isolation_forest"


def test_gateway_resolves_default_static_baseline_config():
    config = MonitorSetup(
        display_name="radar-charger-1",
        reading_ids=["sine"],
        monitoring={
            "strategy": "static_baseline",
            "model_type": "pyod_iforest",
            "model_params": {"n_estimators": 128},
        },
    )

    resolved = config.monitoring.model_dump()

    assert resolved["model_type"] == "pyod_iforest"
    assert resolved["model_params"] == {"n_estimators": 128}
    assert resolved["training_window_size"] == 1200
    assert resolved["calibration_window_size"] == 360
    assert resolved["martingale_config"] == {
        "trackers": [
            {
                "tracker_id": "primary",
                "betting_function": "power",
                "alarm_statistic": "restarted_martingale",
                "epsilon": 0.5,
                "threshold_config": {"mode": "manual", "value": 100.0},
            }
        ],
        "automatic_threshold_calibration": {
            "false_alarm_probability": 0.01,
            "horizon": 1000,
            "simulation_count": 5000,
        },
    }


def _validator(monkeypatch, validated_params=None):
    set_environment(monkeypatch, DATABASE_ENVIRONMENT)
    validator = MagicMock(
        return_value=validated_params or {"n_estimators": 100, "contamination": 0.1}
    )
    monkeypatch.setattr(
        "off_key_tactic_middleware.services.orchestration.radar_environment."
        "validate_model_params",
        validator,
    )
    return validator


def test_tactic_builds_static_environment(monkeypatch):
    validator = _validator(monkeypatch)

    env = build_radar_environment(
        service_id="svc-static",
        validate_params=True,
        config=form_launch(
            container_name="radar",
            mqtt_topics=[
                "telemetry/c1/L1",
                "telemetry/c1/L2",
                "telemetry/c1/L3",
            ],
            strategy="static_baseline",
            model_type="pyod_iforest",
            model_params={"n_estimators": 100},
            performance_config={
                "sensor_key_strategy": "leaf",
                "minimum_hold_seconds": 20.0,
            },
            static_baseline_config={
                "model_type": "pyod_iforest",
                "model_params": {"n_estimators": 100},
                "training_window_size": 120,
                "calibration_window_size": 30,
                "martingale_config": {
                    "trackers": [
                        {
                            "tracker_id": "primary",
                            "betting_function": "power",
                            "alarm_statistic": "restarted_martingale",
                            "epsilon": 0.5,
                            "threshold_config": {
                                "mode": "manual",
                                "value": 100,
                            },
                        }
                    ],
                },
            },
        ),
    )

    static_config = json.loads(env["RADAR_MONITORING_CONFIG"])
    assert env["RADAR_MINIMUM_HOLD_SECONDS"] == "20.0"
    assert env["RADAR_HOLD_INTERVALS"] == "3.0"
    assert json.loads(env["RADAR_MONITORING_CONFIG"])["strategy"] == "static_baseline"
    assert json.loads(env["RADAR_MONITORING_CONFIG"])["model_type"] == "pyod_iforest"
    assert "RADAR_ALIGNMENT_MODE" not in env
    assert "RADAR_PREPROCESSING_STEPS" not in env
    assert "RADAR_ADAPTIVE_STREAM_CONFIG" not in env
    assert static_config["training_window_size"] == 120
    assert static_config["calibration_window_size"] == 30
    assert static_config["martingale_config"]["trackers"] == [
        {
            "tracker_id": "primary",
            "betting_function": "power",
            "alarm_statistic": "restarted_martingale",
            "epsilon": 0.5,
            "threshold_config": {"mode": "manual", "value": 100.0},
        }
    ]
    # The pipeline's parameters are checked, then forwarded unchanged.
    assert static_config["model_params"]["n_estimators"] == 100
    assert validator.call_args.args[1] == static_config["model_params"]
    assert validator.call_args.args[0] == "pyod_iforest"
    assert validator.call_args.kwargs["family"] == "static_pyod"


def test_production_monitor_environment_carries_no_broker_settings(monkeypatch):
    _validator(monkeypatch)
    settings = TacticSettings(
        TACTIC_RADAR_DEFAULT_MQTT_BROKER_HOST="emqx-main",
        TACTIC_RADAR_DEFAULT_MQTT_USE_AUTH=True,
    )
    runtime = SimpleNamespace(
        ENVIRONMENT="production",
        radar_database_url="postgresql+asyncpg://user:pass@postgres/radar",
    )
    config = form_launch(container_name="radar", mqtt_topics=["telemetry/c1/L1"])
    module = "off_key_tactic_middleware.services.orchestration.radar_environment"
    with (
        patch(f"{module}.get_tactic_settings", return_value=settings),
        patch(f"{module}.get_radar_runtime_settings", return_value=runtime),
    ):
        env = build_radar_environment(
            service_id="svc", config=config, validate_params=True
        )
    assert env["ENVIRONMENT"] == "production"
    # Monitors read the stored telemetry log; they never reach a broker.
    assert env["RADAR_SUBSCRIPTION_TOPICS"] == "telemetry/c1/L1"
    assert not [key for key in env if "MQTT" in key]


def test_tactic_builds_adaptive_environment(monkeypatch):
    validator = _validator(monkeypatch, {"num_trees": 2})

    env = build_radar_environment(
        service_id="svc-dynamic",
        validate_params=True,
        config=form_launch(
            container_name="radar",
            mqtt_topics=["telemetry/charger-1/L1"],
            strategy="adaptive_stream",
            model_type="aberrant_online_isolation_forest",
            model_params={"num_trees": 2},
            performance_config={},
            adaptive_stream_config={
                "model_type": "aberrant_online_isolation_forest",
                "model_params": {"num_trees": 2},
                "training_window_size": 1200,
                "calibration_window_size": 360,
            },
        ),
    )

    adaptive = json.loads(env["RADAR_MONITORING_CONFIG"])
    assert json.loads(env["RADAR_MONITORING_CONFIG"])["strategy"] == "adaptive_stream"
    assert "RADAR_STATIC_BASELINE_CONFIG" not in env
    assert adaptive["threshold_config"] == {
        "mode": "calibrated_quantile",
        "quantile": 1.0,
    }
    assert validator.call_args.kwargs["family"] == ("adaptive_aberrant")


def test_tactic_resolves_minimal_adaptive_request_and_rejects_mirror_conflict(
    monkeypatch,
):
    _validator(monkeypatch, {"num_trees": 100})
    env = build_radar_environment(
        service_id="svc-dynamic-default",
        validate_params=True,
        config=form_launch(
            container_name="radar",
            mqtt_topics=["telemetry/charger-1/L1"],
            strategy="adaptive_stream",
            model_type=None,
            model_params={},
            performance_config={},
            adaptive_stream_config=None,
        ),
    )
    assert (
        json.loads(env["RADAR_MONITORING_CONFIG"])["model_type"]
        == "aberrant_online_isolation_forest"
    )

    with pytest.raises(ValueError, match="model_type conflicts"):
        build_radar_environment(
            service_id="svc-dynamic-conflict",
            validate_params=True,
            config=form_launch(
                container_name="radar",
                mqtt_topics=["telemetry/charger-1/L1"],
                strategy="adaptive_stream",
                model_type="aberrant_knn",
                model_params=None,
                performance_config={},
                adaptive_stream_config={
                    "model_type": "aberrant_online_isolation_forest"
                },
            ),
        )


def test_tactic_operational_status_marks_failed_from_docker_exit():
    service = SimpleNamespace(
        status=True,
        operational_stage="operational",
        operational_status={
            "stage": "operational",
            "message_count": 5,
            "processed_message_count": 5,
            "is_stale": False,
        },
        operational_updated_at=datetime.now(UTC),
    )
    status = derive_operational_status(service, "exited")
    assert status["stage"] == "failed"
    assert status["error"] == "RADAR workload is exited"
    assert status["is_stale"] is False


def test_tactic_operational_status_marks_running_heartbeat_stale():
    service = SimpleNamespace(
        status=True,
        operational_stage="collecting_training",
        operational_status={
            "stage": "collecting_training",
            "message_count": 10,
            "processed_message_count": 8,
            "is_stale": False,
        },
        operational_updated_at=datetime.now(UTC) - timedelta(seconds=180),
    )
    status = derive_operational_status(service, "running")
    assert status["stage"] == "collecting_training"
    assert status["is_stale"] is True
    assert status["detail"] == "Runtime heartbeat is stale"
