"""Integration-style tests for monitor performance config forwarding."""

import inspect
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from off_key_api_gateway.api.v1.monitors import (
    MonitoringServiceConfig,
    PerformanceConfig as GatewayPerformanceConfig,
    TacticError,
    _resolve_effective_start_config,
    delete_monitoring_service,
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
    assert resolved["static_baseline_config"]["calibration_window_size"] == 360
    assert resolved["static_baseline_config"]["martingale_config"] == {
        "method": "power",
        "epsilon": 0.5,
        "alpha": 0.01,
    }
    assert "fdr_config" not in resolved["static_baseline_config"]
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


def test_gateway_top_level_performance_config_updates_adaptive_config():
    config = MonitoringServiceConfig(
        container_name="radar-charger-1",
        service_type="radar",
        mqtt_topics=["charger/+/live-telemetry/sine"],
        strategy="adaptive_stream",
        performance_config=GatewayPerformanceConfig(
            heuristic_enabled=True,
            heuristic_window_size=600,
            heuristic_min_samples=80,
            heuristic_tail_alpha=0.004,
            alignment_mode="strict_barrier",
            sensor_key_strategy="top_level",
            sensor_freshness_seconds=15.0,
        ),
        adaptive_stream_config={
            "model_type": "knn",
            "model_params": {"k": 7, "window_size": 400, "warm_up": 25},
            "preprocessing_steps": [],
            "performance_config": {
                "heuristic_enabled": False,
                "heuristic_window_size": 420,
                "heuristic_min_samples": 40,
                "heuristic_tail_alpha": 0.01,
                "alignment_mode": "strict_barrier",
                "sensor_key_strategy": "leaf",
                "sensor_freshness_seconds": 45.0,
            },
        },
    )

    resolved = _resolve_effective_start_config(config)

    assert resolved["performance_config"]["sensor_key_strategy"] == "top_level"
    assert resolved["performance_config"]["sensor_freshness_seconds"] == 15.0
    nested_performance = resolved["adaptive_stream_config"]["performance_config"]
    assert nested_performance["sensor_key_strategy"] == "top_level"
    assert nested_performance["sensor_freshness_seconds"] == 15.0
    assert nested_performance["heuristic_window_size"] == 600


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


@pytest.mark.asyncio
async def test_gateway_stop_validates_identifier():
    handler = inspect.unwrap(stop_monitoring_service)

    with pytest.raises(HTTPException) as exc_info:
        await handler(request=_build_request(), container_name=None, container_id=None)
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException) as exc_info:
        await handler(
            request=_build_request(),
            container_name="radar-a",
            container_id="ctr-a",
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_gateway_stop_forwards_container_identifier():
    mock_stop = AsyncMock(return_value={"status": "stopped", "message": "ok"})
    with patch(
        "off_key_api_gateway.api.v1.monitors.tactic.stop_radar_service",
        mock_stop,
    ):
        handler = inspect.unwrap(stop_monitoring_service)
        response = await handler(
            request=_build_request(),
            container_name=None,
            container_id="ctr-1",
        )

    assert response["status"] == "stopped"
    mock_stop.assert_awaited_once_with(container_name=None, container_id="ctr-1")


@pytest.mark.asyncio
async def test_gateway_delete_uses_service_id_endpoint():
    mock_delete = AsyncMock(return_value={"status": "deleted", "service_id": "svc-1"})
    with patch(
        "off_key_api_gateway.api.v1.monitors.tactic.delete_radar_service",
        mock_delete,
    ):
        handler = inspect.unwrap(delete_monitoring_service)
        response = await handler(request=_build_request(), service_id="svc-1")

    assert response["status"] == "deleted"
    assert response["service_id"] == "svc-1"
    mock_delete.assert_awaited_once_with("svc-1")


@pytest.mark.asyncio
async def test_gateway_delete_preserves_tactic_error_status():
    mock_delete = AsyncMock(
        side_effect=TacticError(
            "missing",
            status=404,
            body={"detail": "RADAR service not found"},
        )
    )
    with patch(
        "off_key_api_gateway.api.v1.monitors.tactic.delete_radar_service",
        mock_delete,
    ):
        handler = inspect.unwrap(delete_monitoring_service)
        with pytest.raises(HTTPException) as exc_info:
            await handler(request=_build_request(), service_id="missing")

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


def test_tactic_build_radar_environment_canonicalizes_adaptive_config(monkeypatch):
    model_registry = MagicMock()
    model_registry.validate_model_params.return_value = {
        "n_estimators": 64,
        "contamination": 0.1,
    }
    model_registry.validate_preprocessing_steps.return_value = [
        {"type": "standard_scaler", "params": {}}
    ]

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
        model_params={"n_estimators": 32},
        preprocessing_steps=[],
        mqtt_config={},
        anomaly_thresholds={},
        performance_config={
            "sensor_key_strategy": "top_level",
            "sensor_freshness_seconds": 15.0,
            "batch_size": 11,
        },
        static_baseline_config={},
        adaptive_stream_config={
            "model_type": "isolation_forest",
            "model_params": {"n_estimators": 32},
            "preprocessing_steps": [
                {"type": "moving_average", "params": {"window_size": 3}}
            ],
            "performance_config": {
                "heuristic_enabled": True,
                "heuristic_window_size": 480,
                "heuristic_min_samples": 70,
                "heuristic_tail_alpha": 0.006,
                "alignment_mode": "strict_barrier",
                "sensor_key_strategy": "leaf",
                "sensor_freshness_seconds": 45.0,
            },
        },
    )

    adaptive_config = json.loads(env["RADAR_ADAPTIVE_STREAM_CONFIG"])

    assert env["RADAR_BATCH_SIZE"] == "11"
    assert env["RADAR_SENSOR_KEY_STRATEGY"] == "top_level"
    assert env["RADAR_SENSOR_FRESHNESS_SECONDS"] == "15.0"
    assert adaptive_config["model_params"] == {
        "n_estimators": 64,
        "contamination": 0.1,
    }
    assert adaptive_config["preprocessing_steps"] == [
        {"type": "standard_scaler", "params": {}}
    ]
    assert adaptive_config["performance_config"]["sensor_key_strategy"] == "top_level"
    assert adaptive_config["performance_config"]["sensor_freshness_seconds"] == 15.0
    assert adaptive_config["performance_config"]["heuristic_window_size"] == 480


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
            "calibration_window_size": 30,
            "martingale_config": {
                "method": "power",
                "alpha": 0.01,
                "epsilon": 0.5,
            },
        },
        adaptive_stream_config={},
    )

    static_config = json.loads(env["RADAR_STATIC_BASELINE_CONFIG"])

    assert env["RADAR_MONITORING_STRATEGY"] == "static_baseline"
    assert env["RADAR_MODEL_TYPE"] == "pyod_iforest"
    assert env["RADAR_PREPROCESSING_STEPS"] == "[]"
    assert static_config["training_window_size"] == 120
    assert static_config["calibration_window_size"] == 30
    assert static_config["martingale_config"] == {
        "method": "power",
        "epsilon": 0.5,
        "alpha": 0.01,
    }
    assert "fdr_config" not in static_config
    assert static_config["model_params"] == {
        "n_estimators": 100,
        "contamination": 0.1,
    }
    assert model_registry.validate_model_params.call_args.args[0] == "pyod_iforest"


def test_tactic_build_radar_environment_accepts_legacy_fdr_config(monkeypatch):
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

    assert static_config["calibration_window_size"] == 30
    assert "fdr_config" not in static_config
    assert static_config["martingale_config"] == {
        "method": "power",
        "epsilon": 0.5,
        "alpha": 0.01,
    }


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
        operational_updated_at=datetime.now(timezone.utc),
    )

    status = RadarOrchestrationService._derive_operational_status(service, "exited")

    assert status["stage"] == "failed"
    assert status["error"] == "Docker workload is exited"
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
        operational_updated_at=datetime.now(timezone.utc) - timedelta(seconds=180),
    )

    status = RadarOrchestrationService._derive_operational_status(service, "running")

    assert status["stage"] == "collecting_training"
    assert status["is_stale"] is True
    assert status["detail"] == "Runtime heartbeat is stale"
