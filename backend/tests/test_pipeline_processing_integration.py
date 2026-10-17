"""Production graph execution over real MQTT, PostgreSQL and signed snapshots."""

from __future__ import annotations

import asyncio
import json
import signal
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from amqtt.client import MQTTClient
from off_key_core.db.migrate import apply_migrations
from off_key_core.db.models import MonitoringService
from off_key_core.db.pipelines import MonitoringPipeline, PipelineRevision, PipelineRun
from off_key_core.models.pipelines import (
    compile_pipeline,
    execution_fingerprint,
    pipeline_catalog_id,
)
from off_key_mqtt_radar import database as radar_database
from off_key_mqtt_radar.admission import (
    RadarAdmissionSettings,
    require_monitor_admission,
)
from off_key_mqtt_radar.config.config import (
    AnomalyDetectionConfig,
    clear_radar_settings_cache,
)
from off_key_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache
from off_key_mqtt_radar.execution_errors import FatalExecutionError
from off_key_mqtt_radar.pipelines.adaptive import AdaptivePipelineDetectionService
from off_key_mqtt_radar.service import RadarService
from sqlalchemy import insert, text

from .test_adaptive_pipeline_runtime import _config
from .test_radar_mqtt_integration import mqtt_broker, wait_until

SERVICE_ID = "pipeline-integration-service"


@asynccontextmanager
async def pipeline_environment(disposable_database, monkeypatch):
    """Bind real dependencies through the same environment contract as Swarm."""
    execution = _config().pipeline.model_copy(deep=True)
    for binding in execution.bindings:
        binding.input_key = binding.slot_id
    execution.fingerprint = execution_fingerprint(
        execution.definition, execution.bindings
    )
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.execute(
            insert(MonitoringPipeline).values(
                id="pipeline",
                name="Branched integration",
                description="",
                archived=False,
                version=1,
                draft=execution.definition.model_dump(mode="json"),
                layout={},
            )
        )
        connection.execute(
            insert(PipelineRevision).values(
                id=execution.revision_id,
                pipeline_id="pipeline",
                number=1,
                definition=execution.definition.model_dump(mode="json"),
                fingerprint=compile_pipeline(execution.definition).fingerprint,
                catalog_id=pipeline_catalog_id(),
            )
        )
        connection.execute(
            insert(MonitoringService).values(
                id=SERVICE_ID,
                container_name="radar-pipeline-integration",
                mqtt_topic=[item.accepted_topic for item in execution.bindings],
                status=True,
                desired_state="running",
                lifecycle_version=1,
                operational_stage="starting",
            )
        )
        connection.execute(
            insert(PipelineRun).values(
                id=execution.run_id,
                service_id=SERVICE_ID,
                revision_id=execution.revision_id,
                execution=execution.model_dump(mode="json"),
                launch_config={},
                layout={},
                status="running",
            )
        )
    for name in (
        "RADAR_CONFIG_FILE",
        "RADAR_MONITORING_CONFIG",
        "RADAR_MONITORING_STRATEGY",
        "RADAR_MODEL_TYPE",
        "RADAR_MODEL_PARAMS",
        "RADAR_STATIC_BASELINE_CONFIG",
        "RADAR_ADAPTIVE_STREAM_CONFIG",
    ):
        monkeypatch.delenv(name, raising=False)
    async with mqtt_broker() as (_, port):
        settings = {
            "ENVIRONMENT": "development",
            "SERVICE_ID": SERVICE_ID,
            "RADAR_LIFECYCLE_VERSION": "1",
            "RADAR_PIPELINE_CONFIG": execution.model_dump_json(),
            "RADAR_SUBSCRIPTION_TOPICS": ",".join(
                item.accepted_topic for item in execution.bindings
            ),
            "RADAR_MQTT_BROKER_HOST": "127.0.0.1",
            "RADAR_MQTT_BROKER_PORT": str(port),
            "RADAR_MQTT_USE_AUTH": "false",
            "RADAR_MQTT_USE_TLS": "false",
            "RADAR_SENSOR_KEY_STRATEGY": "full_hierarchy",
            "RADAR_DATABASE_URL": disposable_database.url.set(
                drivername="postgresql+asyncpg"
            ).render_as_string(hide_password=False),
            "RADAR_DB_WRITE_ENABLED": "true",
            "RADAR_CHECKPOINT_STORAGE": "database",
            "RADAR_CHECKPOINT_SECRET": "disposable-pipeline-checkpoint-key",
            "RADAR_CHECKPOINT_INTERVAL": "1",
            "RADAR_HEALTH_CHECK_INTERVAL": "5",
            "RADAR_RATE_LIMIT_PER_MINUTE": "0",
        }
        for key, value in settings.items():
            monkeypatch.setenv(key, value)
        clear_radar_settings_cache()
        clear_radar_runtime_settings_cache()
        monkeypatch.setattr(radar_database, "_radar_async_session_factory", None)
        sessions = radar_database.get_radar_async_session_factory()
        publisher = MQTTClient(client_id="pipeline-integration-publisher")
        try:
            await publisher.connect(f"mqtt://127.0.0.1:{port}")
            yield execution, sessions, publisher
        finally:
            await publisher.disconnect()
            await sessions.kw["bind"].dispose()
            clear_radar_settings_cache()
            clear_radar_runtime_settings_cache()


@asynccontextmanager
async def supervised_service():
    """Exercise the actual supervisor, restoring this test process's signals."""
    handlers = {
        kind: signal.getsignal(kind) for kind in (signal.SIGINT, signal.SIGTERM)
    }
    service = RadarService()
    runner = asyncio.create_task(service.run())
    try:
        async with asyncio.timeout(20):
            while not service.is_running:
                if runner.done():
                    await runner
                await asyncio.sleep(0.01)
        yield service, runner
    finally:
        service.shutdown_event.set()
        async with asyncio.timeout(20):
            await asyncio.gather(runner, return_exceptions=True)
        for kind, handler in handlers.items():
            signal.signal(kind, handler)


async def publish_observation(execution, publisher, index):
    timestamp = datetime.now(UTC)
    data = {"a": float(index), "b": float(index**2), "temperature": 20.0 + index}
    for binding in execution.bindings:
        await publisher.publish(
            binding.accepted_topic,
            json.dumps(
                {
                    "value": data[binding.slot_id],
                    "timestamp": timestamp.isoformat(),
                }
            ).encode(),
            qos=1,
        )
    return data, timestamp


async def checkpoint_at(sessions, count):
    async with asyncio.timeout(15):
        while True:
            async with sessions() as session:
                row = (
                    (
                        await session.execute(
                            text(
                                "SELECT * FROM radar_runtime_checkpoints "
                                "WHERE service_id=:id"
                            ),
                            {"id": SERVICE_ID},
                        )
                    )
                    .mappings()
                    .first()
                )
            if row is not None and row["processed_count"] >= count:
                return dict(row)
            await asyncio.sleep(0.01)


async def prime_service(execution, sessions, publisher, service):
    for index in range(1, 8):
        await publish_observation(execution, publisher, index)
        await checkpoint_at(sessions, index)
    assert service.detector.primary_service.operational_count == 1


def inject_mutating_failure(monkeypatch, primary):
    terminal = primary.pipeline.model
    original_learn = terminal.learn_one

    def mutate_then_fail(data):
        original_learn(data)  # Real model mutation precedes the injected fault.
        raise RuntimeError("injected terminal update failure")

    monkeypatch.setattr(terminal, "learn_one", mutate_then_fail)
    return terminal


async def test_real_mqtt_graph_restores_numeric_state_and_coherent_preview(
    disposable_database, monkeypatch
):
    async with pipeline_environment(disposable_database, monkeypatch) as (
        execution,
        sessions,
        publisher,
    ):
        async with supervised_service() as (service, _):
            await prime_service(execution, sessions, publisher, service)
            record = await checkpoint_at(sessions, 7)
            snapshot = service._checkpoint_codec.decode(record)
            config = AnomalyDetectionConfig.model_validate(
                service.config.model_dump(
                    include=set(AnomalyDetectionConfig.model_fields)
                )
            )
            reference = AdaptivePipelineDetectionService.from_checkpoint_data(
                snapshot.detector, config, automatic_checkpoints=False
            )
        async with supervised_service() as (replacement, _):
            primary = replacement.detector.primary_service
            assert replacement.recovery_status["restored"]
            assert primary.processed_count == 7
            data, timestamp = await publish_observation(execution, publisher, 8)
            expected = reference.process_data_point(data)
            await checkpoint_at(sessions, 8)
            actual = await replacement._detector_runtime.call(
                primary.get_pipeline_state
            )
            observation = actual["observation"]
            assert observation["sequence_number"] == 8
            assert observation["timestamp"] == timestamp.isoformat()
            assert set(observation["input_timestamps"].values()) == {
                timestamp.isoformat()
            }
            model = observation["passes"]["score"]["model"]
            assert model["input"] == pytest.approx(expected.processed_features)
            assert model["input"]["temperature"] == data["temperature"]
            assert model["output"] == pytest.approx(expected.anomaly_score)
            async with sessions() as session:
                evidence = (
                    (
                        await session.execute(
                            text(
                                "SELECT timestamp, anomaly_score, input_timestamps "
                                "FROM monitoring_evidence WHERE service_id=:id "
                                "AND sequence_number=2"
                            ),
                            {"id": SERVICE_ID},
                        )
                    )
                    .mappings()
                    .one()
                )
            assert evidence["timestamp"] == timestamp
            assert evidence["anomaly_score"] == pytest.approx(expected.anomaly_score)
            assert set(evidence["input_timestamps"].values()) == {timestamp.isoformat()}


async def test_mutating_model_failure_preserves_checkpoint_and_fences_restart(
    disposable_database, monkeypatch
):
    async with (
        pipeline_environment(disposable_database, monkeypatch) as (
            execution,
            sessions,
            publisher,
        ),
        supervised_service() as (service, runner),
    ):
        await prime_service(execution, sessions, publisher, service)
        previous = await checkpoint_at(sessions, 7)
        primary = service.detector.primary_service
        terminal = inject_mutating_failure(monkeypatch, primary)
        network_client = service.mqtt_client.client
        await publish_observation(execution, publisher, 8)
        with pytest.raises(RuntimeError, match="managed persistence failure"):
            async with asyncio.timeout(20):
                await runner
        assert isinstance(service._fatal_error, FatalExecutionError)
        assert not service.is_running
        assert network_client._thread is None
        assert terminal.window["temperature"][-1] == 28.0
        with pytest.raises(FatalExecutionError):
            primary.export_checkpoint()
        async with sessions() as session:
            current = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM radar_runtime_checkpoints "
                            "WHERE service_id=:id"
                        ),
                        {"id": SERVICE_ID},
                    )
                )
                .mappings()
                .one()
            )
            run = (
                (
                    await session.execute(
                        text(
                            "SELECT status, error, ended_at "
                            "FROM monitoring_pipeline_runs WHERE id=:id"
                        ),
                        {"id": execution.run_id},
                    )
                )
                .mappings()
                .one()
            )
            stage = await session.scalar(
                text("SELECT operational_stage FROM services WHERE id=:id"),
                {"id": SERVICE_ID},
            )
            failed_status = await session.scalar(
                text("SELECT operational_status FROM services WHERE id=:id"),
                {"id": SERVICE_ID},
            )
            evidence_count = await session.scalar(
                text("SELECT count(*) FROM monitoring_evidence WHERE service_id=:id"),
                {"id": SERVICE_ID},
            )
        for key in ("payload", "signature", "processed_count", "saved_at"):
            assert current[key] == previous[key]
        assert evidence_count == 1
        assert run["status"] == stage == "failed"
        assert "injected terminal update failure" in run["error"]
        assert run["ended_at"] is not None
        assert failed_status["pipeline_state"]["nodes"]["model"]["state"] == "failed"
        assert failed_status["coverage"]["has_gaps"]
        with pytest.raises(RuntimeError, match="running monitor intent"):
            await require_monitor_admission(
                settings=RadarAdmissionSettings(
                    SERVICE_ID=SERVICE_ID, RADAR_LIFECYCLE_VERSION=1
                ),
                session_factory=sessions,
            )
        restart = RadarService()
        with pytest.raises(RuntimeError, match="running monitor intent"):
            await restart.start()
        assert restart.mqtt_client is None
        assert restart.detector is None


async def test_fatal_failure_retries_durable_fence_without_processing_or_checkpointing(
    disposable_database, monkeypatch
):
    async with (
        pipeline_environment(disposable_database, monkeypatch) as (
            execution,
            sessions,
            publisher,
        ),
        supervised_service() as (service, runner),
    ):
        await prime_service(execution, sessions, publisher, service)
        previous = await checkpoint_at(sessions, 7)
        primary = service.detector.primary_service
        terminal = inject_mutating_failure(monkeypatch, primary)
        writer = service.database_writer
        monkeypatch.setenv("RADAR_CHECKPOINT_TIMEOUT_SECONDS", "0.05")
        monkeypatch.setenv("RADAR_FATAL_PERSIST_RETRY_SECONDS", "0.02")
        clear_radar_runtime_settings_cache()
        async with writer._flush_lock:
            await publish_observation(execution, publisher, 8)
            await wait_until(lambda: service._fatal_error is not None)
            # This holds a real writer lock across multiple actual timeout and
            # retry intervals, without replacing PostgreSQL or writer methods.
            await asyncio.sleep(0.15)
            assert not runner.done()
            assert not service.shutdown_event.is_set()
            assert not service._checkpoint_ready
            assert primary.processed_count == 7
            assert primary.pipeline.model_updates == 5
            await publish_observation(execution, publisher, 9)
            await asyncio.sleep(0.05)
            assert terminal.window["temperature"][-1] == 28.0
            assert primary.pipeline.model_updates == 5
            async with sessions() as session:
                pending = (
                    (
                        await session.execute(
                            text(
                                "SELECT payload, signature, processed_count, saved_at "
                                "FROM radar_runtime_checkpoints WHERE service_id=:id"
                            ),
                            {"id": SERVICE_ID},
                        )
                    )
                    .mappings()
                    .one()
                )
                status = await session.scalar(
                    text("SELECT status FROM monitoring_pipeline_runs WHERE id=:id"),
                    {"id": execution.run_id},
                )
            assert status == "running"
            for key in ("payload", "signature", "processed_count", "saved_at"):
                assert pending[key] == previous[key]
        with pytest.raises(RuntimeError, match="managed persistence failure"):
            async with asyncio.timeout(20):
                await runner
        async with sessions() as session:
            status = await session.scalar(
                text("SELECT status FROM monitoring_pipeline_runs WHERE id=:id"),
                {"id": execution.run_id},
            )
        assert status == "failed"
        with pytest.raises(RuntimeError, match="running monitor intent"):
            await require_monitor_admission(
                settings=RadarAdmissionSettings(
                    SERVICE_ID=SERVICE_ID, RADAR_LIFECYCLE_VERSION=1
                ),
                session_factory=sessions,
            )
