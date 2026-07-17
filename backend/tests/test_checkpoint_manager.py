from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from off_key_core.schemas.radar import StaticBaselineConfig
from off_key_mqtt_radar.checkpoint_manager import CheckpointManager
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


@pytest.mark.asyncio
async def test_service_falls_back_to_older_valid_checkpoint(monkeypatch):
    attempts = []
    restored = MagicMock(processed_count=42)
    monkeypatch.setattr(
        "off_key_mqtt_radar.tactic_client.validate_model_params",
        lambda model_type, params: params,
    )

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
    service.config = SimpleNamespace(
        strategy="static_baseline",
        static_baseline_config=StaticBaselineConfig(),
        subscription_topics=[],
        sensor_key_strategy="full_hierarchy",
        alignment_mode="strict_barrier",
        batch_size=100,
        batch_timeout=1.0,
        memory_limit_mb=1000,
        checkpoint_interval=10000,
    )
    service.checkpoint_manager = manager
    service.required_sensors = set()
    service.state_cache = None
    service._log_context = {"service": "radar"}

    await service._setup_anomaly_detection()

    assert attempts == ["newest.pkl", "older.pkl"]
    manager.cleanup_lock.assert_called_once()
    assert service.detector.primary_service is restored
