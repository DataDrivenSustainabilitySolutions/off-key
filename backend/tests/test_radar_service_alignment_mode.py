"""Tests for RADAR service alignment mode setup from subscription topics."""

from types import SimpleNamespace

from off_key_mqtt_radar import service as service_module
from off_key_mqtt_radar.service import RadarService


def _build_radar_config(subscription_topics):
    return SimpleNamespace(
        memory_limit_mb=500,
        max_feature_count=100,
        max_string_length=1000,
        health_check_interval=30.0,
        subscription_topics=subscription_topics,
        sensor_key_strategy="full_hierarchy",
        sensor_freshness_seconds=30.0,
    )


def test_radar_service_enables_alignment_for_explicit_sensor_topics(monkeypatch):
    settings = SimpleNamespace(
        config=_build_radar_config(
            [
                "charger/+/live-telemetry/sine",
                "charger/+/live-telemetry/cosine",
            ]
        )
    )
    monkeypatch.setattr(service_module, "get_radar_settings", lambda: settings)

    radar_service = RadarService()

    assert radar_service.required_sensors == {"sine", "cosine"}
    assert radar_service.state_cache is not None


def test_radar_service_disables_alignment_for_wildcard_subscription(monkeypatch):
    settings = SimpleNamespace(
        config=_build_radar_config(["charger/+/live-telemetry/#"])
    )
    monkeypatch.setattr(service_module, "get_radar_settings", lambda: settings)

    radar_service = RadarService()

    assert radar_service.required_sensors == set()
    assert radar_service.state_cache is None
