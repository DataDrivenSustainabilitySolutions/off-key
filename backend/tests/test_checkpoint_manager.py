from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from off_key_mqtt_radar.checkpoint_manager import CheckpointManager
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig, MQTTRadarConfig
from off_key_mqtt_radar.detector import StaticConformalDetectionService
from off_key_mqtt_radar.service import RadarService


def _runtime(secret: bytes = b"") -> SimpleNamespace:
    return SimpleNamespace(
        RADAR_CHECKPOINT_DIR="unused",
        SERVICE_ID="unused",
        checkpoint_secret_bytes=secret,
    )


def test_checkpoint_manager_saves_and_loads_one_atomic_envelope(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "off_key_mqtt_radar.checkpoint_manager.get_radar_checkpoint_settings",
        lambda: _runtime(b"secret"),
    )
    manager = CheckpointManager(checkpoint_dir=str(tmp_path), service_id="service-a")

    checkpoint_path = manager.save({"processed_count": 42}, processed_count=42)

    assert manager.load(checkpoint_path) == {"processed_count": 42}
    assert list(tmp_path.glob("*.tmp-*")) == []
    assert list(tmp_path.glob("*.sig")) == []


def test_static_checkpoint_before_config_consolidation_remains_readable(monkeypatch):
    checkpoint = {
        "strategy": "static_baseline",
        "static_state": "collecting",
        "processed_count": 21,
        "training_buffer": [{"L1": 1.5}],
        "schema_signature": (
            "b9e29f162055df516aa44c3dfc9cc9826681f3109c83d597872893b7857b78d1"
        ),
    }
    monkeypatch.setattr(CheckpointManager, "load", lambda self, path: checkpoint)
    config = AnomalyDetectionConfig(subscription_topics=["device/evCharger/c1/L1"])

    restored = StaticConformalDetectionService.from_checkpoint("legacy.pkl", config)
    try:
        assert restored.processed_count == 21
        assert restored.training_buffer == [{"L1": 1.5}]
    finally:
        restored.shutdown()


@pytest.mark.asyncio
async def test_service_falls_back_to_older_valid_checkpoint(monkeypatch):
    attempts = []
    restored = MagicMock(processed_count=42)

    def restore(path, config):
        attempts.append(path)
        if path == "newest.pkl":
            raise ValueError("corrupt checkpoint")
        return restored

    monkeypatch.setattr(
        StaticConformalDetectionService,
        "from_checkpoint",
        staticmethod(restore),
    )
    manager = MagicMock()
    manager.candidate_paths.return_value = ["newest.pkl", "older.pkl"]
    manager.claim.return_value = True

    service = object.__new__(RadarService)
    service.config = MQTTRadarConfig()
    service.checkpoint_manager = manager
    service.required_sensors = set()
    service.state_cache = None
    service._log_context = {"service": "radar"}

    await service._setup_anomaly_detection()

    assert attempts == ["newest.pkl", "older.pkl"]
    manager.cleanup_lock.assert_called_once()
    assert service.detector.primary_service is restored
