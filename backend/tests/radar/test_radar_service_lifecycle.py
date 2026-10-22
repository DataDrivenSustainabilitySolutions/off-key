import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_mqtt_radar import service as radar_service_module
from off_key_mqtt_radar.database import DatabaseWriter
from off_key_mqtt_radar.execution_errors import FatalExecutionError
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


def _radar_service(monkeypatch) -> RadarService:
    config = SimpleNamespace(
        memory_limit_mb=500,
        max_feature_count=100,
        max_string_length=1000,
        health_check_interval=30.0,
        subscription_topics=["telemetry/+/#"],
        sensor_key_strategy="full_hierarchy",
        sensor_freshness_seconds=30.0,
        observation_max_age_seconds=30.0,
        observation_future_tolerance_seconds=5.0,
        alignment_max_skew_seconds=5.0,
    )
    monkeypatch.setattr(
        radar_service_module,
        "get_radar_settings",
        lambda: SimpleNamespace(config=config),
    )
    return RadarService()


@pytest.mark.asyncio
async def test_radar_service_run_reraises_startup_failure(monkeypatch):
    radar_service = _radar_service(monkeypatch)
    radar_service.start = AsyncMock(side_effect=RuntimeError("startup failed"))
    radar_service.stop = AsyncMock()

    monkeypatch.setattr(radar_service_module.signal, "signal", lambda *args: None)

    with pytest.raises(RuntimeError, match="startup failed"):
        await radar_service.run()

    radar_service.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_radar_service_stop_cleans_up_partially_started_components(
    monkeypatch,
):
    radar_service = _radar_service(monkeypatch)
    stopped = []

    def component(name, error=None):
        async def stop():
            stopped.append(name)
            if error is not None:
                raise error

        return SimpleNamespace(stop=stop)

    radar_service.health_monitor = component("health_monitor")
    radar_service.mqtt_client = component("mqtt_client", RuntimeError("broker"))
    radar_service.database_writer = component("database_writer")

    await radar_service.stop()

    # Ingestion stops first; a failing component does not skip the rest.
    assert stopped == ["health_monitor", "mqtt_client", "database_writer"]
    assert radar_service.mqtt_client is None
    assert radar_service.database_writer is None


@pytest.mark.asyncio
async def test_cancelled_message_handler_finishes_processing_before_reraising(
    monkeypatch,
):
    """Shutdown must not interrupt a message between model update and evidence."""
    radar_service = _radar_service(monkeypatch)
    started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def process(message):
        started.set()
        await release.wait()
        finished.set()

    radar_service._process_one_message = process
    handler = asyncio.create_task(radar_service._handle_mqtt_message(object()))
    await started.wait()

    handler.cancel()
    await asyncio.sleep(0)
    assert not handler.done()
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await handler
    assert finished.is_set()


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


@pytest.mark.parametrize(
    ("adaptive_state", "expected_stage", "expected_progress"),
    [
        ("warmup", "collecting_training", {"current": 3, "target": 10}),
        ("calibrating", "collecting_calibration", {"current": 2, "target": 4}),
        ("operational", "operational", None),
        ("failed", "failed", None),
    ],
)
def test_adaptive_detector_operational_stage_mapping(
    adaptive_state,
    expected_stage,
    expected_progress,
):
    monitor = HealthMonitor()
    monitor.start_time = datetime.now()
    monitor.set_components(
        detector=_FakeDetector(
            {
                "strategy": "adaptive_stream",
                "state": adaptive_state,
                "warmup_count": 3,
                "training_window_size": 10,
                "calibration_count": 2,
                "calibration_window_size": 4,
            }
        ),
        message_processor=_FakeMessageProcessor(
            {"message_count": 5, "processed_message_count": 5}
        ),
    )

    operational = monitor.get_health_status().metrics["operational_status"]

    assert operational["stage"] == expected_stage
    assert operational.get("progress") == expected_progress
    if adaptive_state == "failed":
        assert operational["detail"] == "Adaptive stream detector failed"


def test_health_status_uses_one_metric_snapshot_and_reduces_alerts():
    monitor = HealthMonitor()
    monitor.start_time = datetime.now()
    message_processor = MagicMock()
    message_processor.get_metrics.return_value = {
        "message_count": 10,
        "processed_message_count": 8,
        "anomaly_count": 2,
        "anomaly_rate": 0.2,
        "error_count": 2,
        "error_rate": 0.2,
    }
    monitor.set_components(
        mqtt_client=SimpleNamespace(
            get_health_status=lambda: {
                "status": "unhealthy",
                "reason": "disconnected",
            }
        ),
        database_writer=SimpleNamespace(
            get_health_status=lambda: {"status": "disabled"}
        ),
        detector=_FakeDetector({}, state="degraded"),
        memory_manager=SimpleNamespace(
            max_memory_mb=100,
            get_memory_usage=lambda: 95.0,
        ),
        message_processor=message_processor,
    )

    status = monitor.get_health_status()

    assert status.status == "degraded"
    assert status.active_alerts == [
        "mqtt_disconnected",
        "detector_degraded",
        "high_memory_usage",
        "high_error_rate",
    ]
    assert status.metrics["processed_message_count"] == 8
    assert status.metrics["memory_usage_mb"] == 95.0
    message_processor.get_metrics.assert_called_once()

    snapshot = monitor.build_metrics_snapshot(status)
    assert snapshot["total_messages_processed"] == 8
    assert snapshot["total_anomalies_detected"] == 2
    message_processor.get_metrics.assert_called_once()


@pytest.mark.asyncio
async def test_health_monitor_ends_on_shutdown_signal_without_a_final_check():
    monitor = HealthMonitor(health_check_interval=60)
    monitor._perform_health_check = AsyncMock()
    shutdown = asyncio.Event()
    await monitor.start(shutdown)
    await asyncio.sleep(0)

    shutdown.set()
    try:
        # asyncio.wait does not cancel on timeout; the loop swallows cancellation.
        done, _ = await asyncio.wait({monitor._health_check_task}, timeout=1)
        assert done == {monitor._health_check_task}
        monitor._perform_health_check.assert_not_awaited()
    finally:
        await monitor.stop()


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
        service_id="svc-1",
    )

    await writer.write_heartbeat(
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


@pytest.mark.asyncio
async def test_failed_execution_stops_health_publication_without_errors(
    caplog, monkeypatch
):
    """Quarantine publishes no heartbeat and leaves a valid recovery status."""
    radar_service = _radar_service(monkeypatch)
    writer = SimpleNamespace(
        write_heartbeat=AsyncMock(),
        get_health_status=lambda: {"status": "healthy"},
    )
    monitor = HealthMonitor()
    monitor.start_time = datetime.now()
    monitor.set_components(
        database_writer=writer,
        recovery_status=lambda: radar_service.recovery_status,
    )
    radar_service.health_monitor = monitor
    radar_service.recovery_status = {"storage": "database", "restored": True}

    await radar_service._fail_execution(FatalExecutionError("model mutated"))
    await monitor._perform_health_check()

    assert radar_service.shutdown_event.is_set()
    writer.write_heartbeat.assert_not_awaited()
    assert "radar.health_check_failed" not in caplog.text
    monitor.get_health_status()
