import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from off_key_mqtt_radar import service as radar_service_module
from off_key_mqtt_radar.database import DatabaseWriter
from off_key_mqtt_radar.health_monitor import HealthMonitor
from off_key_mqtt_radar.service import RadarService


class _FakeMessageProcessor:
    def __init__(self, metrics):
        self.metrics = metrics

    def get_metrics(self):
        return self.metrics


class _FakeDetector:
    def __init__(self, stats, state="healthy"):
        self.stats = stats
        self.state = state

    def get_health_info(self):
        return {
            "state": self.state,
            "primary_service_stats": self.stats,
        }


@pytest.mark.asyncio
async def test_radar_service_run_reraises_startup_failure(monkeypatch):
    radar_service = object.__new__(RadarService)
    radar_service.start = AsyncMock(side_effect=RuntimeError("startup failed"))
    radar_service.stop = AsyncMock()
    radar_service.shutdown_event = AsyncMock()

    monkeypatch.setattr(radar_service_module.signal, "signal", lambda *args: None)

    with pytest.raises(RuntimeError, match="startup failed"):
        await RadarService.run(radar_service)

    radar_service.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_radar_service_stop_cleans_up_partially_started_components():
    radar_service = object.__new__(RadarService)
    mqtt_client = SimpleNamespace(stop=AsyncMock())
    database_writer = SimpleNamespace(stop=AsyncMock())

    radar_service.is_running = False
    radar_service.shutdown_event = asyncio.Event()
    radar_service._log_context = {}
    radar_service.config_watcher = None
    radar_service.config_reloader = object()
    radar_service.mqtt_client = mqtt_client
    radar_service.detector = None
    radar_service.database_writer = database_writer
    radar_service.message_processor = None
    radar_service.health_monitor = None
    radar_service.checkpoint_manager = SimpleNamespace(cleanup_lock=MagicMock())

    await RadarService.stop(radar_service)

    mqtt_client.stop.assert_awaited_once()
    database_writer.stop.assert_awaited_once()
    radar_service.checkpoint_manager.cleanup_lock.assert_called_once()
    assert radar_service.mqtt_client is None
    assert radar_service.database_writer is None


@pytest.mark.parametrize(
    ("static_state", "expected_stage", "expected_progress"),
    [
        ("collecting", "collecting_training", {"current": 3, "target": 10}),
        ("calibrating", "collecting_calibration", {"current": 2, "target": 4}),
        ("training", "training", None),
        ("ready", "operational", None),
        ("failed", "failed", None),
    ],
)
def test_static_detector_operational_stage_mapping(
    static_state,
    expected_stage,
    expected_progress,
):
    monitor = HealthMonitor()
    monitor.start_time = datetime.now()
    monitor.set_components(
        detector=_FakeDetector(
            {
                "strategy": "static_baseline",
                "state": static_state,
                "training_collected_samples": 3,
                "training_window_size": 10,
                "calibration_collected_samples": 2,
                "calibration_window_size": 4,
            }
        ),
        message_processor=_FakeMessageProcessor(
            {
                "message_count": 5,
                "processed_message_count": 5,
                "last_alignment_status": "aligned_emit",
            }
        ),
    )

    operational = monitor.get_health_status().metrics["operational_status"]

    assert operational["stage"] == expected_stage
    assert operational.get("progress") == expected_progress
    assert operational["message_count"] == 5
    assert operational["processed_message_count"] == 5
    assert operational["last_alignment_status"] == "aligned_emit"
    assert operational["is_stale"] is False


def test_adaptive_detector_waits_until_first_processed_input():
    monitor = HealthMonitor()
    monitor.start_time = datetime.now()
    monitor.set_components(
        detector=_FakeDetector({"strategy": "adaptive_stream"}),
        message_processor=_FakeMessageProcessor(
            {
                "message_count": 2,
                "processed_message_count": 0,
                "last_alignment_status": "waiting_for_all",
            }
        ),
    )

    waiting = monitor.get_health_status().metrics["operational_status"]
    assert waiting["stage"] == "waiting_for_data"
    assert waiting["message_count"] == 2
    assert waiting["processed_message_count"] == 0
    assert waiting["last_alignment_status"] == "waiting_for_all"

    monitor.set_components(
        detector=_FakeDetector({"strategy": "adaptive_stream"}),
        message_processor=_FakeMessageProcessor(
            {
                "message_count": 3,
                "processed_message_count": 1,
                "last_alignment_status": "direct_pass_through",
            }
        ),
    )

    operational = monitor.get_health_status().metrics["operational_status"]
    assert operational["stage"] == "operational"
    assert operational["processed_message_count"] == 1


@pytest.mark.asyncio
async def test_database_writer_updates_service_operational_status(monkeypatch):
    class _Session:
        def __init__(self):
            self.executed = []
            self.committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def add(self, _model):
            return None

        async def execute(self, statement, params=None):
            self.executed.append((str(statement), params or {}))

        async def commit(self):
            self.committed = True

    session = _Session()
    writer = DatabaseWriter(
        SimpleNamespace(db_write_enabled=True),
        session_factory=lambda: session,
    )
    monkeypatch.setattr(
        "off_key_mqtt_radar.database.get_radar_checkpoint_settings",
        lambda: SimpleNamespace(SERVICE_ID="svc-1"),
    )

    await writer.write_service_metrics(
        {
            "total_messages_processed": 2,
            "service_status": "healthy",
            "operational_status": {
                "stage": "operational",
                "message_count": 3,
                "processed_message_count": 2,
                "last_alignment_status": "aligned_emit",
                "is_stale": False,
            },
        }
    )

    update = next(
        (
            params
            for statement, params in session.executed
            if "UPDATE services" in statement
        ),
        None,
    )
    assert update is not None
    assert update["service_id"] == "svc-1"
    assert update["stage"] == "operational"
    assert json.loads(update["status_payload"])["processed_message_count"] == 2
    assert session.committed is True
