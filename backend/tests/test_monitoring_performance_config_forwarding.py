"""Integration-style tests for monitor performance config forwarding."""

import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request

from off_key_api_gateway.api.v1.monitors import (
    MonitoringServiceConfig,
    PerformanceConfig as GatewayPerformanceConfig,
    start_monitoring_service,
)
from off_key_tactic_middleware.services.orchestration.radar import (
    RadarOrchestrationService,
)


def _build_request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/monitors/start",
        "headers": [],
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_gateway_start_monitor_forwards_performance_config():
    config = MonitoringServiceConfig(
        container_name="radar-charger-1",
        service_type="radar",
        mqtt_topics=[
            "charger/+/live-telemetry/sine",
            "charger/+/live-telemetry/cosine",
        ],
        model_type="isolation_forest",
        model_params={"n_estimators": 128},
        performance_config=GatewayPerformanceConfig(
            heuristic_enabled=True,
            heuristic_window_size=600,
            heuristic_min_samples=90,
            heuristic_tail_alpha=0.004,
            alignment_mode="strict_barrier",
            sensor_key_strategy="leaf",
            sensor_freshness_seconds=25.0,
        ),
    )

    expected = {
        "service_id": "svc-1",
        "container_id": "ctr-1",
        "container_name": "radar-charger-1",
        "status": "running",
        "mqtt_topics": config.mqtt_topics,
    }

    mock_start = AsyncMock(return_value=expected)
    with patch(
        "off_key_api_gateway.api.v1.monitors.tactic.start_radar_service",
        mock_start,
    ):
        handler = inspect.unwrap(start_monitoring_service)
        response = await handler(request=_build_request(), config=config)

    assert response == expected
    forwarded = mock_start.await_args.kwargs["performance_config"]
    assert mock_start.await_args.kwargs["strategy"] == "adaptive_stream"
    assert forwarded == {
        "heuristic_enabled": True,
        "heuristic_window_size": 600,
        "heuristic_min_samples": 90,
        "heuristic_tail_alpha": 0.004,
        "alignment_mode": "strict_barrier",
        "sensor_key_strategy": "leaf",
        "sensor_freshness_seconds": 25.0,
    }


def test_tactic_build_radar_environment_maps_performance_to_radar_env(monkeypatch):
    model_registry = MagicMock()
    model_registry.validate_model_params.return_value = {"n_estimators": 64}
    model_registry.validate_preprocessing_steps.return_value = []

    monkeypatch.setattr(
        "off_key_tactic_middleware.services.orchestration.radar.get_async_docker",
        lambda: MagicMock(),
    )
    service = RadarOrchestrationService(
        session=AsyncMock(),
        model_registry=model_registry,
    )

    env = service._build_radar_environment(
        service_id="svc-1",
        mqtt_topics=["charger/+/live-telemetry/sine"],
        strategy="adaptive_stream",
        model_type="isolation_forest",
        model_params={"n_estimators": 64},
        preprocessing_steps=[],
        mqtt_config={},
        anomaly_thresholds={},
        performance_config={
            "heuristic_enabled": True,
            "heuristic_window_size": 480,
            "heuristic_min_samples": 70,
            "heuristic_tail_alpha": 0.006,
            "alignment_mode": "strict_barrier",
            "sensor_key_strategy": "top_level",
            "sensor_freshness_seconds": 15.0,
        },
        static_baseline_config={},
        adaptive_stream_config={},
    )

    assert env["RADAR_MONITORING_STRATEGY"] == "adaptive_stream"
    assert env["RADAR_HEURISTIC_ENABLED"] == "true"
    assert env["RADAR_HEURISTIC_WINDOW_SIZE"] == "480"
    assert env["RADAR_HEURISTIC_MIN_SAMPLES"] == "70"
    assert env["RADAR_HEURISTIC_TAIL_ALPHA"] == "0.006"
    assert env["RADAR_ALIGNMENT_MODE"] == "strict_barrier"
    assert env["RADAR_SENSOR_KEY_STRATEGY"] == "top_level"
    assert env["RADAR_SENSOR_FRESHNESS_SECONDS"] == "15.0"


def test_tactic_build_radar_environment_maps_static_strategy_to_radar_env(monkeypatch):
    model_registry = MagicMock()
    model_registry.validate_model_params.return_value = {
        "n_estimators": 100,
        "contamination": 0.1,
    }
    model_registry.validate_preprocessing_steps.return_value = []

    monkeypatch.setattr(
        "off_key_tactic_middleware.services.orchestration.radar.get_async_docker",
        lambda: MagicMock(),
    )
    service = RadarOrchestrationService(
        session=AsyncMock(),
        model_registry=model_registry,
    )

    env = service._build_radar_environment(
        service_id="svc-static",
        mqtt_topics=[
            "charger/+/live-telemetry/L1",
            "charger/+/live-telemetry/L2",
            "charger/+/live-telemetry/L3",
        ],
        strategy="static_baseline",
        model_type="pyod_iforest",
        model_params={"n_estimators": 100},
        preprocessing_steps=[{"type": "standard_scaler", "params": {}}],
        mqtt_config={},
        anomaly_thresholds={},
        performance_config={
            "alignment_mode": "strict_barrier",
            "sensor_key_strategy": "leaf",
            "sensor_freshness_seconds": 20.0,
        },
        static_baseline_config={
            "model_type": "pyod_iforest",
            "model_params": {"n_estimators": 100},
            "training_window_size": 120,
            "calibration_fraction": 0.25,
            "fdr_config": {
                "method": "saffron",
                "alpha": 0.05,
                "wealth": 0.025,
                "lambda_": 0.5,
            },
        },
        adaptive_stream_config={},
    )

    static_config = json.loads(env["RADAR_STATIC_BASELINE_CONFIG"])

    assert env["RADAR_MONITORING_STRATEGY"] == "static_baseline"
    assert env["RADAR_MODEL_TYPE"] == "pyod_iforest"
    assert env["RADAR_PREPROCESSING_STEPS"] == "[]"
    assert static_config["training_window_size"] == 120
    assert static_config["fdr_config"]["method"] == "saffron"
    assert model_registry.validate_model_params.call_args.args[0] == "pyod_iforest"
