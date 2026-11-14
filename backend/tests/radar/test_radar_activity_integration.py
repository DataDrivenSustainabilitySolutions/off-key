"""Exercise activity health with the telemetry log, a real detector and PostgreSQL."""

import asyncio
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from off_key_core.db.migrate import apply_migrations
from off_key_core.db.models import MonitoringService
from off_key_mqtt_radar import service as service_module
from off_key_mqtt_radar.activity import ActivityTracker
from off_key_mqtt_radar.config.config import RadarConfig
from off_key_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache
from off_key_mqtt_radar.database import DatabaseWriter
from off_key_mqtt_radar.health_monitor import HealthMonitor
from off_key_mqtt_radar.models import AnomalyResult, MQTTMessage
from off_key_mqtt_radar.service import RadarService
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.support.form_pipeline import form_radar_config
from tests.support.mqtt import tiny_adaptive_monitoring, wait_until
from tests.support.telemetry_log import log_reading

pytestmark = pytest.mark.radar_integration


@pytest.mark.asyncio
async def test_real_monitor_reports_stale_peer_and_total_silence_and_recovers(
    telemetry_log, monkeypatch
):
    config = form_radar_config(
        tiny_adaptive_monitoring(),
        ["telemetry/activity/a", "telemetry/activity/b"],
        RadarConfig,
        db_write_enabled=False,
        memory_limit_mb=2048,
        minimum_hold_seconds=0.3,
        health_check_interval=0.05,
        log_poll_seconds=0.01,
    )
    monkeypatch.setenv("SERVICE_ID", "activity-monitor")
    clear_radar_runtime_settings_cache()
    monkeypatch.setattr(
        service_module, "get_radar_settings", lambda: SimpleNamespace(config=config)
    )
    monitor = RadarService()

    async def publish(sensor, value):
        await log_reading(
            telemetry_log, f"telemetry/activity/{sensor}", value, datetime.now(UTC)
        )

    def operational():
        return monitor.health_monitor.get_health_status().metrics["operational_status"]

    try:
        await monitor.start()
        # Keep supplying fresh observations through cold model initialization.
        # A burst followed by silence can correctly expire under this test's
        # deliberately short 300 ms minimum hold.
        deadline = time.monotonic() + 30
        index = 0
        while operational()["stage"] != "operational":
            assert time.monotonic() < deadline, operational()
            expected_processed = monitor.message_processor.message_count + 1
            for sensor in ("a", "b"):
                await publish(sensor, index % 5 + 1)
            await wait_until(
                lambda expected=expected_processed: (
                    monitor.message_processor.message_count >= expected
                )
            )
            index += 1
        assert operational()["activity"]["last_inference_at"] is not None
        previous_inference = operational()["activity"]["last_inference_at"]

        async def outlast_every_limit():
            # Each reading's limit is learned from its own arrivals.
            limits = operational()["activity"]["stale_after_seconds"]
            assert set(limits) == {"a", "b"}
            await asyncio.sleep(max(limits.values()) + 0.05)

        await outlast_every_limit()
        received = monitor.message_processor.received_message_count
        await publish("a", 4)
        await wait_until(
            lambda: monitor.message_processor.received_message_count > received
        )
        status = operational()
        assert status["stage"] == "degraded"
        assert status["activity"]["stale_sensors"] == ["b"]
        assert status["activity"]["last_inference_at"] == previous_inference
        assert not status["is_stale"]
        # The observation that would have held b's old value was dropped and
        # counted, so the monitor shows the gap from now on.
        assert status["coverage"]["dropped_by_reason"] == {"stale_reading": 1}
        await publish("b", 4)
        # That drop used up a's value too: the next observation needs a again.
        await publish("a", 5)
        await wait_until(
            lambda: (
                operational()["activity"]["last_inference_at"] != previous_inference
                and not operational()["activity"]["inputs_stalled"]
            )
        )
        # The next snapshot must age inputs even when no more callbacks occur.
        await outlast_every_limit()
        status = operational()
        assert status["activity"]["stale_sensors"] == ["a", "b"]
        assert status["activity"]["inference_stalled"]
        assert status["coverage"]["dropped_by_reason"] == {"stale_reading": 1}
    finally:
        await monitor.stop()
        clear_radar_runtime_settings_cache()


@pytest.mark.asyncio
async def test_blocked_evidence_commit_keeps_reporting_health_on_second_connection(
    disposable_database, monkeypatch
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.execute(
            insert(MonitoringService).values(
                id="activity-writer", container_name="activity-writer", mqtt_topic=[]
            )
        )
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg"),
        pool_size=2,
        max_overflow=0,
    )
    blocker_engine = create_async_engine(engine.url, pool_size=1, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    config = form_radar_config(
        None,
        ["telemetry/charger-sim-1/sine"],
        RadarConfig,
        minimum_hold_seconds=0.1,
        db_batch_timeout=0.05,
    )
    writer = DatabaseWriter(
        config, session_factory=sessions, service_id="activity-writer"
    )
    timestamp = datetime.now(UTC)
    result = AnomalyResult(
        anomaly_score=0.01,
        is_anomaly=False,
        severity="low",
        timestamp=timestamp,
        model_info={},
        raw_data={"a": 1},
        topic="telemetry/entity/a",
        charger_id="entity",
        context={
            "static_conformal": {
                "phase": "ready",
                "p_value": 0.01,
                "tested_count": 1,
                "threshold": 100.0,
            },
            "alignment": {
                "required_sensors": ["a"],
                "input_timestamps": {"a": timestamp.isoformat()},
            },
        },
    )
    tracker = ActivityTracker({"a"})
    tracker.record_input("a", MQTTMessage(topic="telemetry/entity/a", payload=b"{}"))
    tracker.record_result(result)
    health = HealthMonitor()
    health.started_monotonic = time.monotonic()
    health.set_components(
        database_writer=writer,
        message_processor=SimpleNamespace(
            get_metrics=lambda: {
                "message_count": 1,
                "processed_message_count": 1,
                "activity": tracker.snapshot(),
            },
            stale_after_seconds=lambda: {"a": 5.0},
        ),
    )
    try:
        await writer.start()
        async with blocker_engine.connect() as blocker:
            transaction = await blocker.begin()
            await blocker.execute(
                text("LOCK TABLE monitoring_evidence IN ACCESS EXCLUSIVE MODE")
            )
            try:
                await writer.write_result(result)
                await wait_until(
                    lambda: (
                        writer.get_health_status()["reason"] == "persistence_stalled"
                    )
                )
                snapshot = health.build_metrics_snapshot()
                activity = snapshot["operational_status"]["activity"]
                assert activity["persistence_stalled"]
                assert activity.get("last_persisted_at") is None
                # Evidence has one blocked connection. Heartbeat persistence must
                # still succeed so the operator can see the failure promptly.
                async with asyncio.timeout(2):
                    await writer.write_heartbeat(snapshot)
                async with sessions() as session:
                    status = await session.scalar(
                        text(
                            "SELECT operational_status FROM services "
                            "WHERE id='activity-writer'"
                        )
                    )
                assert status["activity"]["persistence_stalled"]
                assert status["stage"] == "degraded"
            finally:
                await transaction.rollback()
        await wait_until(lambda: writer.last_persisted_at is not None)
        assert writer.get_health_status()["oldest_pending_age_seconds"] is None
        assert not health.get_health_status().metrics["activity"]["persistence_stalled"]
    finally:
        await writer.stop()
        await blocker_engine.dispose()
        await engine.dispose()
