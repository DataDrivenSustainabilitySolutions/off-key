"""Authenticate snapshots and recover real detector state from PostgreSQL."""

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest
from off_key_core.db.migrate import apply_migrations, migration_status
from off_key_core.db.models import MonitoringService
from off_key_core.schemas.radar import AdaptiveStreamConfig, StaticBaselineConfig
from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamDetectionService
from off_key_mqtt_radar.config.config import MQTTRadarConfig
from off_key_mqtt_radar.config.runtime import RadarCheckpointSettings
from off_key_mqtt_radar.database import DatabaseWriter
from off_key_mqtt_radar.detector import StaticConformalDetectionService
from off_key_mqtt_radar.runtime_checkpoint import (
    CoverageCheckpoint,
    ProcessorCheckpoint,
    RuntimeCheckpoint,
    RuntimeCheckpointCodec,
)
from off_key_mqtt_radar.service import RadarService
from pydantic import ValidationError
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

SECRET = b"disposable-integration-checkpoint-key"
TEST_FILE = str(Path(__file__).resolve())


def test_durable_development_key_is_stable_and_forbidden_in_production():
    first = RadarCheckpointSettings(
        ENVIRONMENT="development", RADAR_CHECKPOINT_SECRET=""
    )
    second = RadarCheckpointSettings(
        ENVIRONMENT="development", RADAR_CHECKPOINT_SECRET=""
    )
    assert (
        first.durable_checkpoint_secret_bytes == second.durable_checkpoint_secret_bytes
    )
    assert first.durable_checkpoint_secret_bytes
    with pytest.raises(ValidationError, match="RADAR_CHECKPOINT_SECRET"):
        RadarCheckpointSettings(
            ENVIRONMENT="production",
            RADAR_CHECKPOINT_SECRET=first.durable_checkpoint_secret_bytes.decode(),
        )


def _config(strategy="static_baseline"):
    monitoring = (
        StaticBaselineConfig(
            model_params={"n_estimators": 8},
            training_window_size=20,
            calibration_window_size=8,
        )
        if strategy == "static_baseline"
        else AdaptiveStreamConfig(
            model_type="aberrant_knn",
            model_params={"k": 1, "window_size": 8, "warm_up": 1},
            training_window_size=2,
            calibration_window_size=3,
        )
    )
    return MQTTRadarConfig(
        monitoring=monitoring,
        subscription_topics=["telemetry/entity/x"],
        checkpoint_interval=10,
    )


def _detector(config, checkpoint=None):
    cls = (
        StaticConformalDetectionService
        if config.monitoring.strategy == "static_baseline"
        else AdaptiveStreamDetectionService
    )
    return (
        cls(config, automatic_checkpoints=False)
        if checkpoint is None
        else cls.from_checkpoint_data(checkpoint, config, automatic_checkpoints=False)
    )


def _snapshot(detector):
    return RuntimeCheckpoint(
        detector=detector.export_checkpoint(),
        processor=ProcessorCheckpoint(
            received_message_count=detector.processed_count + 2,
            message_count=detector.processed_count,
            anomaly_count=detector.anomaly_count,
        ),
        coverage=CoverageCheckpoint(
            data={
                "has_gaps": True,
                "dropped_message_count": 2,
                "dropped_by_reason": {"queue_full": 2},
            }
        ),
    )


def _observe(detector, value):
    result = detector.process_data_point(
        {"x": float(value)}, topic="telemetry/entity/x", charger_id="entity"
    )
    result.context["alignment"] = {
        "aligned_vector": False,
        "input_timestamps": {"x": result.timestamp.isoformat()},
    }
    return result


def _comparison(result, detector):
    context = result.context.get(
        "static_conformal", result.context.get("adaptive_stream", {})
    )
    return {
        "score": result.anomaly_score,
        "alarm": result.is_anomaly,
        "sequence": context.get("tested_count", context.get("sequence_number")),
        "processed_count": detector.processed_count,
        "state": detector.state.value,
    }


@pytest.mark.parametrize(
    "changed", ["payload", "service_id", "processed_count", "runtime_fingerprint"]
)
def test_managed_checkpoint_verifies_before_deserialization(changed, monkeypatch):
    config = _config("adaptive_stream")
    detector = _detector(config)
    codec = RuntimeCheckpointCodec("monitor", config, SECRET)
    record = codec.encode(_snapshot(detector))
    if changed == "payload":
        record[changed] = b"invalid-pickle"
    elif changed == "processed_count":
        record[changed] += 1
    else:
        record[changed] = "different"
    monkeypatch.setattr(
        "off_key_mqtt_radar.runtime_checkpoint.pickle.loads",
        lambda *_args: pytest.fail("Unauthenticated pickle was deserialized"),
    )
    with pytest.raises(ValueError, match="authentication"):
        codec.decode(record)


def test_authentic_checkpoint_is_bound_to_service_configuration_and_runtime():
    config = _config("adaptive_stream")
    detector = _detector(config)
    codec = RuntimeCheckpointCodec("monitor", config, SECRET)
    record = codec.encode(_snapshot(detector))
    for other in (
        RuntimeCheckpointCodec("another-monitor", config, SECRET),
        RuntimeCheckpointCodec(
            "monitor",
            config.model_copy(update={"sensor_freshness_seconds": 1.0}),
            SECRET,
        ),
    ):
        with pytest.raises(ValueError, match="incompatible"):
            other.decode(record)
    codec.runtime_fingerprint = "another-scientific-runtime"
    with pytest.raises(ValueError, match="incompatible"):
        codec.decode(record)
    with pytest.raises(ValueError, match="secret"):
        RuntimeCheckpointCodec("monitor", config, b"")


def test_empty_adaptive_snapshot_can_resume_first_observation():
    config = _config("adaptive_stream")
    detector = _detector(config)
    codec = RuntimeCheckpointCodec("monitor", config, SECRET)
    restored = _detector(
        config, codec.decode(codec.encode(_snapshot(detector))).detector
    )
    assert restored.feature_keys == []
    assert _comparison(_observe(restored, 1), restored) == _comparison(
        _observe(detector, 1), detector
    )


@pytest.mark.asyncio
async def test_static_fit_restarts_with_preserved_observations():
    config = _config()
    original = _detector(config)
    restored = None
    try:
        for index in range(28):
            _observe(original, index % 7)
        assert original.state.value == "training"
        codec = RuntimeCheckpointCodec("monitor", config, SECRET)
        restored = _detector(
            config, codec.decode(codec.encode(_snapshot(original))).detector
        )
        assert restored.processed_count == 28
        assert len(restored.training_buffer) == 20
        assert len(restored.calibration_buffer) == 8
        deadline = time.monotonic() + 15
        while restored.state.value == "training" and time.monotonic() < deadline:
            restored.refresh_background_state()
            await asyncio.sleep(0.01)
        assert restored.state.value == "ready"
        assert restored.processed_count == 28
        assert restored.training_buffer == []
        assert restored.calibration_buffer == []
    finally:
        original.shutdown()
        if restored:
            restored.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["static_baseline", "adaptive_stream"])
async def test_real_detector_restores_in_replacement_process(
    disposable_database, monkeypatch, strategy
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.execute(
            insert(MonitoringService).values(
                id="monitor",
                container_name="radar-monitor",
                mqtt_topic=["telemetry/entity/x"],
            )
        )
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setenv("SERVICE_ID", "monitor")
    from off_key_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache

    clear_radar_runtime_settings_cache()
    config = _config(strategy)
    detector = _detector(config)
    codec = RuntimeCheckpointCodec("monitor", config, SECRET)
    writer = DatabaseWriter(config, sessions, managed_checkpoints=True)
    try:
        await writer.commit_checkpoint(codec.encode(_snapshot(detector)))
        for index in range(
            config.monitoring.training_window_size
            + config.monitoring.calibration_window_size
        ):
            _observe(detector, index % 7)
        if strategy == "static_baseline":
            deadline = time.monotonic() + 15
            while detector.state.value == "training" and time.monotonic() < deadline:
                detector.refresh_background_state()
                await asyncio.sleep(0.01)
            assert detector.state.value == "ready"
        for value in (0.5, 0.7, 3.0):
            await writer.write_result(_observe(detector, value))
        saved_count = detector.processed_count
        await writer.commit_checkpoint(codec.encode(_snapshot(detector)))
        assert writer.write_queue == []
        async with sessions() as session:
            assert (
                await session.scalar(text("SELECT count(*) FROM monitoring_evidence"))
                == 3
            )
        expected = _comparison(_observe(detector, 2.5), detector)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            TEST_FILE,
            "--replacement-probe",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        output, errors = await asyncio.wait_for(
            process.communicate(
                json.dumps(
                    {
                        "database_url": engine.url.render_as_string(
                            hide_password=False
                        ),
                        "config": config.model_dump(mode="json"),
                    }
                ).encode()
            ),
            timeout=30,
        )
        assert process.returncode == 0, errors.decode(errors="replace")
        actual = json.loads(output.decode().splitlines()[-1])
        assert actual["restored_count"] == saved_count
        assert actual["processor_count"] == saved_count
        assert actual["known_drops"] == 2
        assert actual["next"] == expected
        # Every subsequent checkpoint replaces one bounded row.
        async with sessions() as session:
            assert (
                await session.scalar(
                    text("SELECT count(*) FROM radar_runtime_checkpoints")
                )
                == 1
            )
    finally:
        shutdown = getattr(detector, "shutdown", None)
        if shutdown:
            shutdown()
        await engine.dispose()
        clear_radar_runtime_settings_cache()


@pytest.mark.asyncio
async def test_checkpoint_and_pending_evidence_roll_back_together(
    disposable_database, monkeypatch
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.execute(
            insert(MonitoringService).values(
                id="monitor",
                container_name="radar-monitor",
                mqtt_topic=["telemetry/entity/x"],
            )
        )
    from off_key_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache

    monkeypatch.setenv("SERVICE_ID", "monitor")
    clear_radar_runtime_settings_cache()
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    config = _config("adaptive_stream")
    detector = _detector(config)
    codec = RuntimeCheckpointCodec("monitor", config, SECRET)
    writer = DatabaseWriter(config, sessions, managed_checkpoints=True)
    try:
        await writer.commit_checkpoint(codec.encode(_snapshot(detector)))
        for index in range(5):
            _observe(detector, index)
        await writer.write_result(_observe(detector, 2.5))
        checkpoint = codec.encode(_snapshot(detector))
        with pytest.raises(IntegrityError):
            await writer.commit_checkpoint({**checkpoint, "signature": None})
        assert len(writer.write_queue) == 1
        async with sessions() as session:
            assert (
                await session.scalar(text("SELECT count(*) FROM monitoring_evidence"))
                == 0
            )
            assert (
                await session.scalar(
                    text("SELECT processed_count FROM radar_runtime_checkpoints")
                )
                == 0
            )
        await writer.commit_checkpoint(checkpoint)
        # A corrupted managed snapshot must fail closed before a fresh detector
        # can overwrite the only durable model state.
        async with sessions() as session:
            await session.execute(
                text(
                    "UPDATE radar_runtime_checkpoints SET payload = decode('00', 'hex')"
                )
            )
            await session.commit()
        monkeypatch.setattr(
            "off_key_mqtt_radar.service.get_radar_settings",
            lambda: type("Settings", (), {"config": config})(),
        )
        service = RadarService()
        service._checkpoint_codec = codec
        service.database_writer = writer
        with pytest.raises(ValueError, match="authentication"):
            await service._setup_anomaly_detection()
        assert service.detector is None
        assert service._checkpoint_ready is False
        async with sessions() as session:
            assert (
                await session.scalar(text("SELECT count(*) FROM monitoring_evidence"))
                == 1
            )
            await session.execute(text("DELETE FROM services WHERE id='monitor'"))
            await session.commit()
            assert (
                await session.scalar(
                    text("SELECT count(*) FROM radar_runtime_checkpoints")
                )
                == 0
            )
    finally:
        await engine.dispose()
        clear_radar_runtime_settings_cache()


@pytest.mark.parametrize("ledger", [True, False])
def test_checkpoint_migration_adopts_existing_database_without_path_table_changes(
    disposable_database, ledger
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.execute(text("DROP TABLE radar_runtime_checkpoints"))
        connection.execute(
            text("CREATE TABLE radar_model_checkpoints (checkpoint_path text)")
        )
        connection.execute(
            text("INSERT INTO radar_model_checkpoints VALUES ('preserved.pkl')")
        )
        if ledger:
            connection.execute(
                text("DELETE FROM off_key_schema_migrations WHERE version >= '008_'")
            )
        else:
            connection.execute(text("DROP TABLE off_key_schema_migrations"))
    with disposable_database.begin() as connection:
        assert (
            "008_radar_runtime_checkpoints.sql"
            in migration_status(connection)["pending"]
        )
        apply_migrations(connection)
        assert (
            connection.scalar(
                text("SELECT checkpoint_path FROM radar_model_checkpoints")
            )
            == "preserved.pkl"
        )
        assert apply_migrations(connection)["applied"] == []


async def _replacement_probe():
    request = json.loads(sys.stdin.read())
    config = MQTTRadarConfig.model_validate(request["config"])
    engine = create_async_engine(request["database_url"])
    writer = DatabaseWriter(config, async_sessionmaker(engine))
    try:
        record = await writer.load_checkpoint("monitor")
        snapshot = RuntimeCheckpointCodec("monitor", config, SECRET).decode(record)
        detector = _detector(config, snapshot.detector)
        result = _observe(detector, 2.5)
        print(
            json.dumps(
                {
                    "restored_count": record["processed_count"],
                    "processor_count": snapshot.processor.message_count,
                    "known_drops": snapshot.coverage.data["dropped_message_count"],
                    "next": _comparison(result, detector),
                }
            )
        )
        shutdown = getattr(detector, "shutdown", None)
        if shutdown:
            shutdown()
    finally:
        await engine.dispose()


if __name__ == "__main__" and "--replacement-probe" in sys.argv:
    asyncio.run(_replacement_probe())
