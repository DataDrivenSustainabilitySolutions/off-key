"""Integration-style tests for monitor performance config forwarding."""

import inspect
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
            heuristic_zscore_threshold=4.2,
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
    assert forwarded == {
        "heuristic_enabled": True,
        "heuristic_window_size": 600,
        "heuristic_min_samples": 90,
        "heuristic_zscore_threshold": 4.2,
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
        model_type="isolation_forest",
        model_params={"n_estimators": 64},
        preprocessing_steps=[],
        mqtt_config={},
        anomaly_thresholds={},
        performance_config={
            "heuristic_enabled": True,
            "heuristic_window_size": 480,
            "heuristic_min_samples": 70,
            "heuristic_zscore_threshold": 3.8,
            "sensor_key_strategy": "top_level",
            "sensor_freshness_seconds": 15.0,
        },
    )

    assert env["RADAR_HEURISTIC_ENABLED"] == "true"
    assert env["RADAR_HEURISTIC_WINDOW_SIZE"] == "480"
    assert env["RADAR_HEURISTIC_MIN_SAMPLES"] == "70"
    assert env["RADAR_HEURISTIC_ZSCORE_THRESHOLD"] == "3.8"
    assert env["RADAR_SENSOR_KEY_STRATEGY"] == "top_level"
    assert env["RADAR_SENSOR_FRESHNESS_SECONDS"] == "15.0"
