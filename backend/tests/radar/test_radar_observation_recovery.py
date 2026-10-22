"""Real managed worker replacement rejects retained checkpointed observations."""

import json
import pickle
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from amqtt.client import MQTTClient
from off_key_core.db.migrate import apply_migrations
from off_key_core.db.models import MonitoringService
from off_key_core.schemas.radar import StaticBaselineConfig
from off_key_mqtt_radar import database as database_module
from off_key_mqtt_radar import service as service_module
from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamDetectionService
from off_key_mqtt_radar.config.config import MQTTRadarConfig
from off_key_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache
from off_key_mqtt_radar.database import DatabaseWriter
from off_key_mqtt_radar.detector import StaticConformalDetectionService
from off_key_mqtt_radar.runtime_checkpoint import (
    RuntimeCheckpoint,
    RuntimeCheckpointCodec,
)
from off_key_mqtt_radar.service import RadarService
from pydantic import ValidationError
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.support.mqtt import start_mqtt_broker, tiny_adaptive_monitoring, wait_until

pytestmark = pytest.mark.radar_integration


@pytest.mark.asyncio
@pytest.mark.parametrize("sensors", [("x",), ("a", "b")])
async def test_managed_replacement_rejects_retained_replay_without_partial_frames(
    disposable_database, monkeypatch, sensors
):
    topics = [f"telemetry/entity/{sensor}" for sensor in sensors]
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.execute(
            insert(MonitoringService).values(
                id="retained-monitor",
                container_name="retained-monitor",
                mqtt_topic=topics,
                desired_state="running",
                lifecycle_version=1,
            )
        )
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database_module, "_radar_async_session_factory", sessions)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SERVICE_ID", "retained-monitor")
    monkeypatch.setenv("RADAR_LIFECYCLE_VERSION", "1")
    monkeypatch.setenv("RADAR_CHECKPOINT_SECRET", "retained-integration-secret")
    clear_radar_runtime_settings_cache()
    broker, port = await start_mqtt_broker()
    config = MQTTRadarConfig(
        broker_host="127.0.0.1",
        broker_port=port,
        subscription_topics=topics,
        db_write_enabled=True,
        checkpoint_interval=1,
        observation_max_age_seconds=120,
        health_check_interval=0.1,
        monitoring=tiny_adaptive_monitoring(),
    )
    monkeypatch.setattr(
        service_module, "get_radar_settings", lambda: SimpleNamespace(config=config)
    )
    publisher = MQTTClient(client_id="retained-integration-publisher")
    workers = []
    try:
        await publisher.connect(f"mqtt://127.0.0.1:{port}")
        original = RadarService()
        workers.append(original)
        await original.start()
        for index in range(7):
            timestamp = datetime.now(UTC).isoformat()
            for topic in topics:
                await publisher.publish(
                    topic,
                    json.dumps(
                        {
                            "value": float(index % 3),
                            "timestamp": timestamp,
                        }
                    ).encode(),
                    qos=1,
                    retain=True,
                )
            await wait_until(
                lambda index=index: (
                    original.recovery_status.get("saved_processed_count") == index + 1
                )
            )
        assert original.detector.primary_service.state.value == "operational"
        assert set(
            original.message_processor.export_observation_watermarks()["entity"]
        ) == set(sensors)
        original_processor = original.message_processor
        original_coverage = original.mqtt_client.coverage
        await original.stop()
        duplicate_count = original_coverage.snapshot().dropped_by_reason.get(
            "observation_duplicate", 0
        )

        replacement = RadarService()
        workers.append(replacement)
        await replacement.start()
        await wait_until(
            lambda: (
                replacement.message_processor.received_message_count
                >= original_processor.received_message_count + len(sensors)
            )
        )
        assert replacement.mqtt_client.coverage.snapshot().dropped_by_reason.get(
            "observation_duplicate", 0
        ) >= duplicate_count + len(sensors), (
            replacement.mqtt_client.coverage.snapshot().model_dump(),
            replacement.detector.primary_service.processed_count,
            replacement.message_processor.export_observation_watermarks(),
        )
        assert replacement.recovery_status["restored"] is True
        assert replacement.detector.primary_service.processed_count == 7
        assert replacement.mqtt_client.coverage.snapshot().possible_gap_count >= 1

        # Watermarks reject replay, but never supply a cached feature to the next
        # vector. A new reading is needed from every subscribed sensor.
        timestamp = datetime.now(UTC).isoformat()
        before = replacement.message_processor.received_message_count
        await publisher.publish(
            topics[0],
            json.dumps(
                {
                    "value": 2.5,
                    "timestamp": timestamp,
                }
            ).encode(),
            qos=1,
            retain=True,
        )
        if len(sensors) > 1:
            # Retained QoS deliveries can still be queued after subscription.
            # Wait for this fresh reading's watermark, not an exact aggregate
            # receipt count that another retained delivery can advance past.
            await wait_until(
                lambda: (
                    replacement.message_processor.export_observation_watermarks()
                    .get("entity", {})
                    .get(sensors[0])
                    == datetime.fromisoformat(timestamp).timestamp()
                )
            )
            assert replacement.message_processor.received_message_count >= before + 1
            assert replacement.detector.primary_service.processed_count == 7
            for topic in topics[1:]:
                await publisher.publish(
                    topic,
                    json.dumps(
                        {
                            "value": 2.5,
                            "timestamp": timestamp,
                        }
                    ).encode(),
                    qos=1,
                    retain=True,
                )
        await wait_until(
            lambda: replacement.recovery_status.get("saved_processed_count") == 8
        )
        assert replacement.detector.primary_service.processed_count == 8
    finally:
        for worker in reversed(workers):
            await worker.stop()
        await publisher.disconnect()
        await broker.shutdown()
        await engine.dispose()
        clear_radar_runtime_settings_cache()


@pytest.mark.asyncio
@pytest.mark.parametrize("processed_count", [0, 1])
async def test_managed_restore_requires_history_after_first_observation(
    disposable_database, monkeypatch, processed_count
):
    """An authentic older payload cannot silently reopen a replay boundary."""
    config = MQTTRadarConfig(
        subscription_topics=["telemetry/entity/x"],
        monitoring=tiny_adaptive_monitoring(),
    )
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.execute(
            insert(MonitoringService).values(
                id="history-monitor",
                container_name="history-monitor",
                mqtt_topic=config.subscription_topics,
            )
        )
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SERVICE_ID", "history-monitor")
    clear_radar_runtime_settings_cache()
    monkeypatch.setattr(
        service_module, "get_radar_settings", lambda: SimpleNamespace(config=config)
    )
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    writer = DatabaseWriter(
        config, async_sessionmaker(engine), managed_checkpoints=True
    )
    codec = RuntimeCheckpointCodec(
        "history-monitor", config, b"history-integration-secret"
    )
    detector = AdaptiveStreamDetectionService(config)
    worker = RadarService()
    worker._checkpoint_codec = codec
    worker.database_writer = writer
    restored = None
    try:
        if processed_count:
            detector.process_data_point(
                {"x": 1.0}, topic="telemetry/entity/x", charger_id="entity"
            )
        await writer.commit_checkpoint(
            codec.encode(RuntimeCheckpoint(detector=detector.export_checkpoint()))
        )
        if processed_count:
            with pytest.raises(ValueError, match="missing observation replay history"):
                await worker._setup_anomaly_detection()
        else:
            restored = await worker._setup_anomaly_detection()
            assert restored.restored is True
            assert restored.service.processed_count == 0
            assert worker.recovery_status["restored"] is True
    finally:
        detector.shutdown()
        if restored is not None:
            restored.service.shutdown()
        await engine.dispose()
        clear_radar_runtime_settings_cache()


@pytest.mark.parametrize("strategy", ["static_baseline", "adaptive_stream"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("sensor_freshness_seconds", 10.0),
        ("observation_max_age_seconds", 15.0),
        ("observation_future_tolerance_seconds", 1.0),
        ("alignment_max_skew_seconds", 1.0),
    ],
)
def test_checkpoint_rejects_changed_alignment_policy(
    monkeypatch, strategy, field, value
):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("RADAR_CHECKPOINT_SECRET", "file-policy-integration-secret")
    clear_radar_runtime_settings_cache()
    monitoring = (
        StaticBaselineConfig(training_window_size=20, calibration_window_size=8)
        if strategy == "static_baseline"
        else tiny_adaptive_monitoring()
    )
    config = MQTTRadarConfig(
        monitoring=monitoring, subscription_topics=["telemetry/entity/x"]
    )
    cls = (
        StaticConformalDetectionService
        if strategy == "static_baseline"
        else AdaptiveStreamDetectionService
    )
    detector = cls(config)
    try:
        checkpoint = pickle.loads(pickle.dumps(detector.export_checkpoint()))
        with pytest.raises(
            ValueError, match=r"schema signature|configuration is incompatible"
        ):
            cls.from_checkpoint_data(
                checkpoint, config.model_copy(update={field: value})
            )
    finally:
        detector.shutdown()
        clear_radar_runtime_settings_cache()


def test_checkpoint_rejects_nonfinite_observation_watermarks():
    with pytest.raises(ValidationError):
        RuntimeCheckpoint(
            detector={"processed_count": 0},
            observation_watermarks={"entity": {"x": float("nan")}},
        )
