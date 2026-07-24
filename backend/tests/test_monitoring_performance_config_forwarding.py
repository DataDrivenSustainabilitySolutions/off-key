"""Integration-style tests for the static monitoring start contract."""

import inspect
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from off_key_api_gateway.api.v1.monitors import (
    MonitoringServiceConfig,
    TacticError,
    _resolve_effective_start_config,
    delete_monitoring_service,
    start_monitoring_service,
    stop_monitoring_service,
)
from off_key_api_gateway.api.v1.monitors import (
    PerformanceConfig as GatewayPerformanceConfig,
)
from off_key_tactic_middleware.services.orchestration.radar_environment import (
    build_radar_environment,
)
from off_key_tactic_middleware.services.radar_status import (
    derive_operational_status,
)
from pydantic import ValidationError
from starlette.requests import Request


def _build_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/monitors/start",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )


@pytest.mark.asyncio
async def test_gateway_start_monitor_forwards_static_performance_config():
    config = MonitoringServiceConfig(
        container_name="radar-charger-1",
        service_type="radar",
        mqtt_topics=[
            "charger/charger-1/live-telemetry/sine",
            "charger/charger-1/live-telemetry/cosine",
        ],
        model_type="pyod_iforest",
        model_params={"n_estimators": 128},
        performance_config=GatewayPerformanceConfig(
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
        response = await inspect.unwrap(start_monitoring_service)(
            request=_build_request(), config=config
        )

    assert response == expected
    forwarded = mock_start.await_args.kwargs
    assert forwarded["strategy"] == "static_baseline"
    assert forwarded["performance_config"] == {
        "alignment_mode": "strict_barrier",
        "sensor_key_strategy": "leaf",
        "sensor_freshness_seconds": 25.0,
    }
    assert forwarded["static_baseline_config"]["martingale_config"] == {
        "method": "power",
        "epsilon": 0.5,
        "restarted_ville_threshold": 100.0,
    }


def test_gateway_monitoring_config_rejects_root_wildcard_topic():
    with pytest.raises(ValueError, match="Root wildcard"):
        MonitoringServiceConfig(
            container_name="radar-charger-1",
            mqtt_topics=["#"],
        )


def test_gateway_rejects_dynamic_strategy_and_removed_fields():
    with pytest.raises(ValidationError, match="static_baseline"):
        MonitoringServiceConfig(
            container_name="radar-charger-1",
            mqtt_topics=["charger/+/live-telemetry/sine"],
            strategy="adaptive_stream",
        )

    with pytest.raises(ValidationError, match="adaptive_stream_config"):
        MonitoringServiceConfig(
            container_name="radar-charger-1",
            mqtt_topics=["charger/+/live-telemetry/sine"],
            adaptive_stream_config={},
        )


def test_gateway_resolves_default_static_baseline_config():
    config = MonitoringServiceConfig(
        container_name="radar-charger-1",
        mqtt_topics=["charger/charger-1/live-telemetry/sine"],
        model_type="pyod_iforest",
        model_params={"n_estimators": 128},
    )

    resolved = _resolve_effective_start_config(config)

    assert resolved["model_type"] == "pyod_iforest"
    assert resolved["model_params"] == {"n_estimators": 128}
    assert resolved["static_baseline_config"]["training_window_size"] == 1200
    assert resolved["static_baseline_config"]["calibration_window_size"] == 360
    assert resolved["static_baseline_config"]["martingale_config"] == {
        "method": "power",
        "epsilon": 0.5,
        "restarted_ville_threshold": 100.0,
    }


@pytest.mark.asyncio
async def test_gateway_stop_preserves_tactic_error_status():
    mock_stop = AsyncMock(
        side_effect=TacticError(
            "missing", status=404, body={"detail": "RADAR service not found"}
        )
    )
    with (
        patch(
            "off_key_api_gateway.api.v1.monitors.tactic.stop_radar_service", mock_stop
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await inspect.unwrap(stop_monitoring_service)(
            request=_build_request(), container_name="missing", container_id=None
        )
    assert exc_info.value.status_code == 404


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
        "off_key_api_gateway.api.v1.monitors.tactic.stop_radar_service", mock_stop
    ):
        response = await inspect.unwrap(stop_monitoring_service)(
            request=_build_request(), container_name=None, container_id="ctr-1"
        )
    assert response["status"] == "stopped"
    mock_stop.assert_awaited_once_with(container_name=None, container_id="ctr-1")


@pytest.mark.asyncio
async def test_gateway_delete_uses_service_id_endpoint():
    mock_delete = AsyncMock(return_value={"status": "deleted", "service_id": "svc-1"})
    with patch(
        "off_key_api_gateway.api.v1.monitors.tactic.delete_radar_service", mock_delete
    ):
        response = await inspect.unwrap(delete_monitoring_service)(
            request=_build_request(), service_id="svc-1"
        )
    assert response["status"] == "deleted"
    mock_delete.assert_awaited_once_with("svc-1")


@pytest.mark.asyncio
async def test_gateway_delete_preserves_tactic_error_status():
    mock_delete = AsyncMock(
        side_effect=TacticError(
            "missing", status=404, body={"detail": "RADAR service not found"}
        )
    )
    with (
        patch(
            "off_key_api_gateway.api.v1.monitors.tactic.delete_radar_service",
            mock_delete,
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await inspect.unwrap(delete_monitoring_service)(
            request=_build_request(), service_id="missing"
        )
    assert exc_info.value.status_code == 404


def _model_registry(validated_params=None):
    registry = MagicMock()
    registry.validate_model_params.return_value = validated_params or {
        "n_estimators": 100,
        "contamination": 0.1,
    }
    return registry


def test_tactic_builds_static_environment():
    registry = _model_registry()

    env = build_radar_environment(
        service_id="svc-static",
        mqtt_topics=[
            "charger/+/live-telemetry/L1",
            "charger/+/live-telemetry/L2",
            "charger/+/live-telemetry/L3",
        ],
        strategy="static_baseline",
        model_type="pyod_iforest",
        model_params={"n_estimators": 100},
        mqtt_config={},
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
                "epsilon": 0.5,
                "restarted_ville_threshold": 100,
            },
        },
        model_registry=registry,
    )

    static_config = json.loads(env["RADAR_STATIC_BASELINE_CONFIG"])
    assert env["RADAR_MONITORING_STRATEGY"] == "static_baseline"
    assert env["RADAR_MODEL_TYPE"] == "pyod_iforest"
    assert "RADAR_PREPROCESSING_STEPS" not in env
    assert "RADAR_ADAPTIVE_STREAM_CONFIG" not in env
    assert static_config["training_window_size"] == 120
    assert static_config["calibration_window_size"] == 30
    assert static_config["martingale_config"]["restarted_ville_threshold"] == 100.0
    assert static_config["model_params"] == {
        "n_estimators": 100,
        "contamination": 0.1,
    }
    assert registry.validate_model_params.call_args.args[0] == "pyod_iforest"


def test_tactic_environment_rejects_dynamic_strategy():
    registry = _model_registry()

    with pytest.raises(ValueError, match="dynamic monitoring is not implemented"):
        build_radar_environment(
            service_id="svc-dynamic",
            mqtt_topics=["charger/+/live-telemetry/L1"],
            strategy="adaptive_stream",
            model_type="pyod_iforest",
            model_params={},
            mqtt_config={},
            performance_config={},
            static_baseline_config={},
            model_registry=registry,
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
        operational_updated_at=datetime.now(UTC) - timedelta(seconds=180),
    )
    status = derive_operational_status(service, "running")
    assert status["stage"] == "collecting_training"
    assert status["is_stale"] is True
    assert status["detail"] == "Runtime heartbeat is stale"
