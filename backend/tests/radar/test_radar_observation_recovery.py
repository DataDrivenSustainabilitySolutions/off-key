"""Managed worker replacement replays the telemetry log after its snapshot."""

import pickle
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from off_key_core.db.migrate import apply_migrations
from off_key_core.db.models import MonitoringService
from off_key_core.schemas.radar import StaticBaselineConfig
from off_key_mqtt_radar import service as service_module
from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamDetectionService
from off_key_mqtt_radar.config.config import RadarConfig
from off_key_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache
from off_key_mqtt_radar.database import DatabaseWriter
from off_key_mqtt_radar.detector import StaticConformalDetectionService
from off_key_mqtt_radar.runtime_checkpoint import (
    RuntimeCheckpoint,
    RuntimeCheckpointCodec,
)
from off_key_mqtt_radar.service import RadarService
from pydantic import ValidationError
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.support.form_pipeline import form_radar_config
from tests.support.mqtt import tiny_adaptive_monitoring, wait_until
from tests.support.telemetry_log import log_readings

pytestmark = pytest.mark.radar_integration


async def _evidence_count(sessions) -> int:
    async with sessions() as session:
        return await session.scalar(
            text(
                "SELECT count(*) FROM monitoring_evidence"
                " WHERE service_id = 'replay-monitor'"
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("sensors", [("x",), ("a", "b")])
async def test_replacement_replays_the_log_after_its_checkpoint_exactly_once(
    telemetry_log, monkeypatch, sensors
):
    """A crash rolls back to an older snapshot and readings arrive while the
    monitor is down; its replacement processes every one of them once."""
    topics = [f"telemetry/entity/{sensor}" for sensor in sensors]
    async with telemetry_log() as session:
        await session.execute(
            insert(MonitoringService).values(
                id="replay-monitor",
                container_name="replay-monitor",
                mqtt_topic=topics,
                desired_state="running",
                lifecycle_version=1,
            )
        )
        await session.commit()
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SERVICE_ID", "replay-monitor")
    monkeypatch.setenv("RADAR_LIFECYCLE_VERSION", "1")
    monkeypatch.setenv("RADAR_CHECKPOINT_SECRET", "replay-integration-secret")
    clear_radar_runtime_settings_cache()
    config = form_radar_config(
        tiny_adaptive_monitoring(),
        topics,
        RadarConfig,
        db_write_enabled=True,
        checkpoint_interval=1,
        minimum_hold_seconds=120,
        health_check_interval=0.1,
        log_poll_seconds=0.01,
    )
    monkeypatch.setattr(
        service_module, "get_radar_settings", lambda: SimpleNamespace(config=config)
    )
    start = datetime.now(UTC)

    async def log_round(index):
        received = start + timedelta(seconds=index)
        await log_readings(
            telemetry_log, [(topic, float(index % 3), received) for topic in topics]
        )

    workers = []
    try:
        original = RadarService()
        workers.append(original)
        await original.start()
        rolled_back = None
        for index in range(7):
            await log_round(index)
            await wait_until(
                lambda index=index: (
                    original.recovery_status.get("saved_processed_count") == index + 1
                )
            )
            if index == 4:
                async with telemetry_log() as session:
                    rolled_back = (
                        (
                            await session.execute(
                                text("SELECT * FROM radar_runtime_checkpoints")
                            )
                        )
                        .one()
                        ._asdict()
                    )
        assert original.detector.primary_service.state.value == "operational"
        await wait_until(lambda: original.database_writer.last_persisted_at)
        await original.stop()
        # Evidence of the scored rounds six and seven is already written.
        evidence = await _evidence_count(telemetry_log)
        assert evidence >= 2

        # A hard crash: the durable snapshot is the one after the fifth round.
        async with telemetry_log() as session:
            await session.execute(
                text(
                    "UPDATE radar_runtime_checkpoints SET"
                    " format_version = :format_version,"
                    " configuration_fingerprint = :configuration_fingerprint,"
                    " runtime_fingerprint = :runtime_fingerprint,"
                    " processed_count = :processed_count, saved_at = :saved_at,"
                    " payload = :payload, signature = :signature"
                    " WHERE service_id = :service_id"
                ),
                rolled_back,
            )
            await session.commit()
        # Two rounds arrive while no monitor runs.
        await log_round(7)
        await log_round(8)

        replacement = RadarService()
        workers.append(replacement)
        await replacement.start()
        assert replacement.recovery_status["restored"] is True
        assert replacement.recovery_status["restored_processed_count"] == 5
        await wait_until(
            lambda: replacement.recovery_status.get("saved_processed_count") == 9
        )
        assert replacement.detector.primary_service.processed_count == 9
        coverage = replacement.coverage.snapshot()
        assert coverage.dropped_message_count == 0
        assert coverage.possible_gap_count == 0
        await wait_until(lambda: replacement.database_writer.last_persisted_at)
        await wait_until(
            lambda: not replacement.database_writer.write_queue, deadline_seconds=5
        )
        # Rounds six and seven were scored again but written once; the two
        # rounds logged while the monitor was down add theirs.
        assert await _evidence_count(telemetry_log) == evidence + 2

        # A restore never supplies a cached feature to the next vector: a new
        # reading is needed from every subscribed sensor.
        before = replacement.message_processor.received_message_count
        received = start + timedelta(seconds=9)
        await log_readings(telemetry_log, [(topics[0], 2.5, received)])
        if len(sensors) > 1:
            await wait_until(
                lambda: (
                    replacement.message_processor.received_message_count == before + 1
                )
            )
            assert replacement.detector.primary_service.processed_count == 9
            await log_readings(
                telemetry_log, [(topic, 2.5, received) for topic in topics[1:]]
            )
        await wait_until(
            lambda: replacement.recovery_status.get("saved_processed_count") == 10
        )
        assert replacement.detector.primary_service.processed_count == 10
    finally:
        for worker in reversed(workers):
            await worker.stop()
        clear_radar_runtime_settings_cache()


@pytest.mark.asyncio
@pytest.mark.parametrize("processed_count", [0, 1])
async def test_managed_restore_requires_history_after_first_observation(
    disposable_database, monkeypatch, processed_count
):
    """An authentic older payload cannot silently reopen a replay boundary."""
    config = form_radar_config(
        tiny_adaptive_monitoring(), ["telemetry/entity/x"], RadarConfig
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
            codec.encode(
                RuntimeCheckpoint(detector=detector.export_checkpoint(), log_position=0)
            )
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
        ("hold_intervals", 10.0),
        ("minimum_hold_seconds", 15.0),
        ("future_tolerance_seconds", 1.0),
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
    config = form_radar_config(monitoring, ["telemetry/entity/x"], RadarConfig)
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
            log_position=0,
        )
