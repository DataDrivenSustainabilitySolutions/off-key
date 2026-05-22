"""Integration-style tests for monitor performance config forwarding."""

import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from off_key_api_gateway.api.v1.monitors import (
    MonitoringServiceConfig,
    PerformanceConfig as GatewayPerformanceConfig,
    TacticError,
    _resolve_effective_start_config,
    start_monitoring_service,
    stop_monitoring_service,
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


def test_gateway_monitoring_config_rejects_root_wildcard_topic():
    with pytest.raises(ValueError, match="Root wildcard"):
        MonitoringServiceConfig(
            container_name="radar-charger-1",
            service_type="radar",
            mqtt_topics=["#"],
        )


def test_gateway_resolves_default_static_baseline_config_from_legacy_fields():
    config = MonitoringServiceConfig(
        container_name="radar-charger-1",
        service_type="radar",
        mqtt_topics=["charger/+/live-telemetry/sine"],
        strategy="static_baseline",
        model_type="pyod_iforest",
        model_params={"n_estimators": 128},
    )

    resolved = _resolve_effective_start_config(config)

    assert resolved["model_type"] == "pyod_iforest"
    assert resolved["model_params"] == {"n_estimators": 128}
    assert resolved["preprocessing_steps"] == []
    assert resolved["static_baseline_config"]["model_type"] == "pyod_iforest"
    assert resolved["static_baseline_config"]["model_params"] == {"n_estimators": 128}
    assert resolved["static_baseline_config"]["training_window_size"] == 1200
    assert resolved["adaptive_stream_config"] is None


def test_gateway_static_strategy_does_not_forward_adaptive_stream_config():
    config = MonitoringServiceConfig(
        container_name="radar-charger-1",
        service_type="radar",
        mqtt_topics=["charger/+/live-telemetry/sine"],
        strategy="static_baseline",
        model_type="pyod_iforest",
        adaptive_stream_config={
            "model_type": "knn",
            "model_params": {"k": 7},
        },
    )

    resolved = _resolve_effective_start_config(config)

    assert resolved["static_baseline_config"]["model_type"] == "pyod_iforest"
    assert resolved["adaptive_stream_config"] is None


@pytest.mark.asyncio
async def test_gateway_stop_preserves_tactic_error_status():
    mock_stop = AsyncMock(
        side_effect=TacticError(
            "missing",
            status=404,
            body={"detail": "RADAR service not found"},
        )
    )
    with patch(
        "off_key_api_gateway.api.v1.monitors.tactic.stop_radar_service",
        mock_stop,
    ):
        handler = inspect.unwrap(stop_monitoring_service)
        with pytest.raises(HTTPException) as exc_info:
            await handler(
                request=_build_request(),
                container_name="missing",
                container_id=None,
            )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "RADAR service not found"


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


def test_tactic_build_radar_environment_forwards_naive_fdr_config(monkeypatch):
    model_registry = MagicMock()
    model_registry.validate_model_params.return_value = {"n_estimators": 100}
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
        mqtt_topics=["charger/+/live-telemetry/L1"],
        strategy="static_baseline",
        model_type="pyod_iforest",
        model_params={"n_estimators": 100},
        preprocessing_steps=[],
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
                "method": "naive",
                "cutoff": 0.02,
            },
        },
        adaptive_stream_config={},
    )

    static_config = json.loads(env["RADAR_STATIC_BASELINE_CONFIG"])

    assert static_config["fdr_config"]["method"] == "naive"
    assert static_config["fdr_config"]["cutoff"] == 0.02
