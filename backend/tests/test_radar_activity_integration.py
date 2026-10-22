"""Exercise activity health with real MQTT, a real detector, and TimescaleDB."""

import asyncio
import json
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from amqtt.client import MQTTClient
from off_key_core.db.migrate import apply_migrations
from off_key_core.db.models import MonitoringService
from off_key_mqtt_radar import service as service_module
from off_key_mqtt_radar.activity import ActivityTracker
from off_key_mqtt_radar.config.config import MQTTRadarConfig
from off_key_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache
from off_key_mqtt_radar.database import DatabaseWriter
from off_key_mqtt_radar.health_monitor import HealthMonitor
from off_key_mqtt_radar.models import AnomalyResult, MQTTMessage, ServiceMetrics
from off_key_mqtt_radar.service import RadarService
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.support.mqtt import start_mqtt_broker, tiny_adaptive_monitoring, wait_until


@pytest.mark.asyncio
async def test_real_monitor_reports_stale_peer_and_total_silence_and_recovers(
    tmp_path, monkeypatch
):
    broker, port = await start_mqtt_broker()
    config = MQTTRadarConfig(
        broker_host="127.0.0.1",
        broker_port=port,
        subscription_topics=["telemetry/activity/a", "telemetry/activity/b"],
        db_write_enabled=False,
        # This shared pytest process imports every monorepo/scientific package.
        # Size its real RSS budget separately from the isolated worker budget
        # asserted by the production-image Swarm test, so full GC on every input
        # does not dominate the deliberately short freshness interval below.
        memory_limit_mb=2048,
        sensor_freshness_seconds=0.3,
        health_check_interval=0.05,
        monitoring=tiny_adaptive_monitoring(),
    )
    monkeypatch.setenv("RADAR_CHECKPOINT_STORAGE", "file")
    monkeypatch.setenv("RADAR_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("SERVICE_ID", "activity-monitor")
    clear_radar_runtime_settings_cache()
    monkeypatch.setattr(
        service_module, "get_radar_settings", lambda: SimpleNamespace(config=config)
    )
    monitor = RadarService()
    publisher = MQTTClient(client_id="activity-publisher")

    async def publish(sensor, value):
        await publisher.publish(
            f"telemetry/activity/{sensor}",
            json.dumps(
                {"value": value, "timestamp": datetime.now(UTC).isoformat()}
            ).encode(),
            qos=1,
        )

    def operational():
        return monitor.get_health_status().metrics["operational_status"]

    try:
        await monitor.start()
        await publisher.connect(f"mqtt://127.0.0.1:{port}")
        # Keep supplying fresh observations through cold model initialization.
        # A burst followed by silence can correctly expire in the ingress queue
        # under this test's deliberately short 300 ms freshness policy.
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
        await asyncio.sleep(0.35)
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
        await publish("b", 4)
        await wait_until(lambda: operational()["stage"] == "operational")
        # The next snapshot must age inputs even when no more callbacks occur.
        await asyncio.sleep(0.35)
        status = operational()
        assert status["activity"]["stale_sensors"] == ["a", "b"]
        assert status["activity"]["inference_stalled"]
        assert not status["coverage"]["has_gaps"]
    finally:
        await monitor.stop()
        await publisher.disconnect()
        await broker.shutdown()
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
    monkeypatch.setattr(
        "off_key_mqtt_radar.database.get_radar_checkpoint_settings",
        lambda: SimpleNamespace(SERVICE_ID="activity-writer"),
    )
    monkeypatch.setattr(
        "off_key_mqtt_radar.result_records.get_radar_checkpoint_settings",
        lambda: SimpleNamespace(SERVICE_ID="activity-writer"),
    )
    config = MQTTRadarConfig(sensor_freshness_seconds=0.1, db_batch_timeout=0.05)
    writer = DatabaseWriter(config, session_factory=sessions)
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
    health = HealthMonitor(sensor_freshness_seconds=5.0)
    health.start_time = datetime.now()
    health.set_components(
        database_writer=writer,
        message_processor=SimpleNamespace(
            get_metrics=lambda: {
                "message_count": 1,
                "processed_message_count": 1,
                "activity": tracker.snapshot(),
            }
        ),
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(ServiceMetrics.__table__.create)
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
                    await writer.write_service_metrics(snapshot)
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
