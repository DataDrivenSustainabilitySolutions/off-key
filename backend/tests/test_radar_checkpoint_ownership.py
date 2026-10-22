"""Managed worker overlap is fenced by actual PostgreSQL transactions."""

import asyncio
from contextlib import suppress
from types import SimpleNamespace

import pytest
from off_key_core.db.migrate import apply_migrations
from off_key_core.db.models import MonitoringService
from off_key_core.schemas.radar import AdaptiveStreamConfig
from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamDetectionService
from off_key_mqtt_radar.config.config import MQTTRadarConfig
from off_key_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache
from off_key_mqtt_radar.database import CheckpointOwnershipLost, DatabaseWriter
from off_key_mqtt_radar.runtime_checkpoint import (
    RuntimeCheckpoint,
    RuntimeCheckpointCodec,
)
from off_key_mqtt_radar.service import RadarService
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def config():
    return MQTTRadarConfig(
        subscription_topics=["telemetry/entity/x"],
        monitoring=AdaptiveStreamConfig(
            model_type="aberrant_knn",
            model_params={"k": 1, "window_size": 8, "warm_up": 1},
            training_window_size=2,
            calibration_window_size=3,
        ),
    )


def observe(detector, value):
    result = detector.process_data_point(
        {"x": float(value)}, topic="telemetry/entity/x", charger_id="entity"
    )
    result.context["alignment"] = {
        "aligned_vector": False,
        "input_timestamps": {"x": result.timestamp.isoformat()},
    }
    return result


def snapshot(codec, detector):
    return codec.encode(RuntimeCheckpoint(detector=detector.export_checkpoint()))


@pytest.fixture
async def store(disposable_database, monkeypatch):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.execute(
            insert(MonitoringService).values(
                id="overlap-monitor",
                container_name="overlap-monitor",
                mqtt_topic=["telemetry/entity/x"],
            )
        )
    monkeypatch.setenv("SERVICE_ID", "overlap-monitor")
    clear_radar_runtime_settings_cache()
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg"),
        pool_size=2,
        max_overflow=0,
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        clear_radar_runtime_settings_cache()


@pytest.fixture
async def owner(store):
    settings = config()
    codec = RuntimeCheckpointCodec(
        "overlap-monitor", settings, b"overlap-integration-secret"
    )
    detector = AdaptiveStreamDetectionService(settings)
    writer = DatabaseWriter(settings, store, managed_checkpoints=True)
    try:
        for index in range(5):
            observe(detector, index)
        await writer.commit_checkpoint(snapshot(codec, detector))
        yield writer, codec, detector
    finally:
        detector.shutdown()


@pytest.mark.asyncio
async def test_late_old_writer_cannot_roll_back_replacement_checkpoint(store):
    settings = config()
    codec = RuntimeCheckpointCodec(
        "overlap-monitor", settings, b"overlap-integration-secret"
    )
    old_detector = AdaptiveStreamDetectionService(settings)
    replacement_detector = None
    old_writer = DatabaseWriter(settings, store, managed_checkpoints=True)
    replacement_writer = DatabaseWriter(settings, store, managed_checkpoints=True)
    try:
        for index in range(5):
            observe(old_detector, index)
        await old_writer.commit_checkpoint(snapshot(codec, old_detector))
        record = await replacement_writer.load_checkpoint("overlap-monitor")
        replacement_detector = AdaptiveStreamDetectionService.from_checkpoint_data(
            codec.decode(record).detector, settings
        )
        await replacement_writer.write_result(observe(replacement_detector, 5))
        await replacement_writer.write_result(observe(replacement_detector, 6))
        await replacement_writer.commit_checkpoint(
            snapshot(codec, replacement_detector)
        )
        stale_result = observe(old_detector, 7)
        await old_writer.write_result(stale_result)
        with pytest.raises(RuntimeError, match="ownership"):
            await old_writer.commit_checkpoint(snapshot(codec, old_detector))
        assert old_writer.write_queue == [stale_result]
        async with store() as session:
            assert (
                await session.scalar(
                    text("SELECT processed_count FROM radar_runtime_checkpoints")
                )
                == 7
            )
            assert (
                await session.scalar(text("SELECT count(*) FROM monitoring_evidence"))
                == 2
            )
    finally:
        old_detector.shutdown()
        if replacement_detector is not None:
            replacement_detector.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["background_batch", "retry_batch", "heartbeat"])
async def test_stale_writer_cannot_commit_outputs_or_status(store, owner, operation):
    old_writer, codec, detector = owner
    replacement_writer = DatabaseWriter(config(), store, managed_checkpoints=True)
    await replacement_writer.load_checkpoint("overlap-monitor")
    await replacement_writer.commit_checkpoint(snapshot(codec, detector))
    await replacement_writer.write_heartbeat(
        {"operational_status": {"stage": "operational"}}
    )
    result = observe(detector, 6)
    await old_writer.write_result(result)
    if operation == "heartbeat":
        await old_writer.write_heartbeat({"operational_status": {"stage": "failed"}})
    else:
        with pytest.raises(CheckpointOwnershipLost):
            if operation == "background_batch":
                await old_writer._flush_batch()
            else:
                await old_writer._retry_failed_batch(batch_snapshot=[result])
    assert old_writer.write_queue == [result]
    assert old_writer.get_health_status()["reason"] == "checkpoint_ownership_lost"
    with pytest.raises(CheckpointOwnershipLost):
        await old_writer.write_result(result)
    async with store() as session:
        assert (
            await session.scalar(text("SELECT count(*) FROM monitoring_evidence")) == 0
        )
        assert (
            await session.scalar(text("SELECT operational_stage FROM services"))
            == "operational"
        )


@pytest.mark.asyncio
async def test_concurrent_initial_snapshots_have_one_winner(store):
    settings = config()
    codec = RuntimeCheckpointCodec(
        "overlap-monitor", settings, b"overlap-integration-secret"
    )
    detector = AdaptiveStreamDetectionService(settings)
    writers = [
        DatabaseWriter(settings, store, managed_checkpoints=True) for _ in range(2)
    ]
    try:
        assert await asyncio.gather(
            *(writer.load_checkpoint("overlap-monitor") for writer in writers)
        ) == [None, None]
        records = [snapshot(codec, detector) for _ in writers]
        results = await asyncio.gather(
            *(
                writer.commit_checkpoint(record)
                for writer, record in zip(writers, records, strict=True)
            ),
            return_exceptions=True,
        )
        assert sum(result is None for result in results) == 1
        assert (
            sum(isinstance(result, CheckpointOwnershipLost) for result in results) == 1
        )
        winner = next(index for index, result in enumerate(results) if result is None)
        async with store() as session:
            assert (
                await session.scalar(
                    text("SELECT signature FROM radar_runtime_checkpoints")
                )
                == records[winner]["signature"]
            )
    finally:
        detector.shutdown()


@pytest.mark.asyncio
async def test_deleted_snapshot_cannot_be_recreated_by_retired_owner(store, owner):
    writer, codec, detector = owner
    async with store() as session:
        await session.execute(text("DELETE FROM radar_runtime_checkpoints"))
        await session.commit()
    with pytest.raises(CheckpointOwnershipLost):
        await writer.commit_checkpoint(snapshot(codec, detector))
    async with store() as session:
        assert (
            await session.scalar(text("SELECT count(*) FROM radar_runtime_checkpoints"))
            == 0
        )


async def wait_for_database_lock(blocker, query_fragment):
    async with asyncio.timeout(5):
        while True:  # PostgreSQL exposes no asynchronous lock-wait notification.
            await blocker.execute(text("SELECT pg_stat_clear_snapshot()"))
            if await blocker.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname=current_database() AND wait_event_type='Lock' "
                    "AND query ILIKE :fragment"
                ),
                {"fragment": f"%{query_fragment}%"},
            ):
                return
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_blocked_checkpoint_keeps_heartbeat_and_serializes_takeover(store, owner):
    writer, codec, detector = owner
    replacement = DatabaseWriter(config(), store, managed_checkpoints=True)
    await replacement.load_checkpoint("overlap-monitor")
    replacement_snapshot = snapshot(codec, detector)
    await writer.write_result(observe(detector, 6))
    blocker_engine = create_async_engine(
        store.kw["bind"].url, pool_size=1, max_overflow=0
    )
    committing = None
    replacing = None
    try:
        async with blocker_engine.connect() as blocker:
            transaction = await blocker.begin()
            await blocker.execute(
                text("LOCK TABLE monitoring_evidence IN ACCESS EXCLUSIVE MODE")
            )
            try:
                committing = asyncio.create_task(
                    writer.commit_checkpoint(snapshot(codec, detector))
                )
                await wait_for_database_lock(blocker, "INSERT INTO monitoring_evidence")
                async with asyncio.timeout(2):
                    await writer.write_heartbeat(
                        {"operational_status": {"stage": "degraded"}}
                    )
                assert not writer._ownership_error
                assert (
                    await blocker.scalar(text("SELECT operational_stage FROM services"))
                    == "degraded"
                )
                replacing = asyncio.create_task(
                    replacement.commit_checkpoint(replacement_snapshot)
                )
                await wait_for_database_lock(
                    blocker, "UPDATE radar_runtime_checkpoints"
                )
                assert not replacing.done()
            finally:
                await transaction.rollback()
        await committing
        with pytest.raises(CheckpointOwnershipLost):
            await replacing
        async with store() as session:
            assert (
                await session.scalar(
                    text("SELECT processed_count FROM radar_runtime_checkpoints")
                )
                == 6
            )
            assert (
                await session.scalar(text("SELECT count(*) FROM monitoring_evidence"))
                == 1
            )
    finally:
        for task in (committing, replacing):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError, CheckpointOwnershipLost):
                    await task
        await blocker_engine.dispose()


@pytest.mark.asyncio
async def test_detected_ownership_loss_stops_worker_before_model_advancement(
    store, owner, monkeypatch
):
    writer, codec, detector = owner
    replacement = DatabaseWriter(config(), store, managed_checkpoints=True)
    await replacement.load_checkpoint("overlap-monitor")
    await replacement.commit_checkpoint(snapshot(codec, detector))
    with pytest.raises(CheckpointOwnershipLost):
        await writer.commit_checkpoint(snapshot(codec, detector))
    settings = config().model_copy(update={"health_check_interval": 0.1})
    monkeypatch.setattr(
        "off_key_mqtt_radar.service.get_radar_settings",
        lambda: SimpleNamespace(config=settings),
    )
    worker = RadarService()
    worker._checkpoint_codec = codec
    worker._checkpoint_ready = True
    worker.database_writer = writer
    async with asyncio.timeout(2):
        await worker._checkpoint_loop()
    assert worker.shutdown_event.is_set()
    assert isinstance(worker._fatal_error, CheckpointOwnershipLost)
    assert detector.processed_count == 5


@pytest.mark.asyncio
async def test_fenced_heartbeat_wakes_blocked_producer_without_writer_task(
    store, owner
):
    writer, codec, detector = owner
    writer.config = writer.config.model_copy(update={"max_queue_size": 1})
    first = observe(detector, 6)
    await writer.write_result(first)
    waiting = asyncio.create_task(writer.write_result(observe(detector, 7)))
    try:
        await asyncio.sleep(0)
        assert not waiting.done()
        replacement = DatabaseWriter(config(), store, managed_checkpoints=True)
        await replacement.load_checkpoint("overlap-monitor")
        await replacement.commit_checkpoint(snapshot(codec, detector))
        await writer.write_heartbeat({"operational_status": {"stage": "failed"}})
        async with asyncio.timeout(2):
            with pytest.raises(CheckpointOwnershipLost):
                await waiting
        assert writer.write_queue == [first]
    finally:
        waiting.cancel()
        with suppress(asyncio.CancelledError, CheckpointOwnershipLost):
            await waiting


@pytest.mark.asyncio
async def test_managed_evidence_cannot_commit_before_initial_checkpoint_claim(store):
    settings = config()
    detector = AdaptiveStreamDetectionService(settings)
    writer = DatabaseWriter(settings, store, managed_checkpoints=True)
    try:
        for index in range(5):
            observe(detector, index)
        result = observe(detector, 6)
        await writer.write_result(result)
        with pytest.raises(CheckpointOwnershipLost):
            await writer._flush_batch()
        assert writer.write_queue == [result]
        async with store() as session:
            assert (
                await session.scalar(text("SELECT count(*) FROM monitoring_evidence"))
                == 0
            )
    finally:
        detector.shutdown()
