"""Actual signed-state writers serialize fatal status with stale heartbeats."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from off_key_core.db.models import MonitoringService, PipelineActivation, PipelineRun
from off_key_core.schemas.pipelines import (
    PipelineActivationRequest,
    PipelineExecutionConfig,
)
from off_key_mqtt_radar import database as radar_database
from off_key_mqtt_radar.config.config import MQTTRadarConfig
from off_key_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache
from off_key_mqtt_radar.database import DatabaseWriter
from off_key_mqtt_radar.pipelines.static import StaticPipelineDetectionService
from off_key_mqtt_radar.runtime_checkpoint import (
    CoverageCheckpoint,
    ProcessorCheckpoint,
    RuntimeCheckpoint,
    RuntimeCheckpointCodec,
)
from off_key_tactic_middleware.services.pipelines.activation import PipelineActivations
from sqlalchemy import text

from . import test_monitoring_pipelines_integration as monitoring_fixture

pipeline_database = monitoring_fixture.pipeline_database


@pytest_asyncio.fixture
async def signed_graph_writer(pipeline_database, monkeypatch):
    monkeypatch.setattr(
        radar_database, "_radar_async_session_factory", pipeline_database
    )
    async with pipeline_database() as session:
        _, revision = await monitoring_fixture.published_design(session)
        activation = await PipelineActivations(session).submit(
            PipelineActivationRequest(
                revision_id=revision.id,
                bindings={"value": "current"},
                display_name="Failure status race",
                idempotency_key="failure-status-race",
            )
        )
        run = await session.get(PipelineRun, activation.run_id)
        run.status = "running"
        execution = PipelineExecutionConfig.model_validate(run.execution)
        session.add(
            MonitoringService(
                id=activation.service_id,
                container_name=run.launch_config["container_name"],
                mqtt_topic=run.launch_config["mqtt_topics"],
                status=True,
                desired_state="running",
                lifecycle_version=1,
                operational_stage="operational",
                operational_updated_at=datetime.now(UTC),
                launch_config=run.launch_config,
            )
        )
        await session.commit()
    monkeypatch.setenv("SERVICE_ID", activation.service_id)
    clear_radar_runtime_settings_cache()
    config = MQTTRadarConfig(pipeline=execution)
    detector = StaticPipelineDetectionService(config, automatic_checkpoints=False)
    writer = DatabaseWriter(
        config, session_factory=pipeline_database, managed_checkpoints=True
    )
    try:
        codec = RuntimeCheckpointCodec(
            activation.service_id, config, b"disposable-failure-status-secret"
        )
        snapshot = codec.encode(
            RuntimeCheckpoint(
                detector=detector.export_checkpoint(),
                processor=ProcessorCheckpoint(),
                coverage=CoverageCheckpoint(data={}),
            )
        )
        assert await writer.load_checkpoint(activation.service_id) is None
        await writer.commit_checkpoint(snapshot)
        yield writer, pipeline_database, activation, snapshot, codec
    finally:
        detector.shutdown()
        clear_radar_runtime_settings_cache()


def healthy_metrics():
    return {
        "service_status": "healthy",
        "operational_status": {
            "stage": "operational",
            "updated_at": datetime.now(UTC),
            "pipeline_state": {"nodes": {"detector": {"state": "ready"}}},
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("timely", [True, False])
async def test_startup_uses_first_database_receipt_even_when_controller_is_delayed(
    signed_graph_writer, timely
):
    writer, sessions, activation, _, _ = signed_graph_writer
    if timely:
        await writer.write_heartbeat(healthy_metrics())
    async with sessions.begin() as session:
        service = await session.get(MonitoringService, activation.service_id)
        row = await session.get(PipelineActivation, activation.id)
        row.phase = "awaiting_heartbeat"
        first = service.operational_status.get("first_heartbeat_at")
        row.heartbeat_deadline = (
            datetime.fromisoformat(first) + timedelta(milliseconds=1)
            if timely
            else datetime.now(UTC) - timedelta(seconds=1)
        )
    await asyncio.sleep(0.02)
    metrics = healthy_metrics()
    # A sender cannot forge an earlier database receipt.
    metrics["operational_status"]["first_heartbeat_at"] = "2000-01-01T00:00:00Z"
    await writer.write_heartbeat(metrics)
    async with sessions() as session:
        service = await session.get(MonitoringService, activation.service_id)
        row = await session.get(PipelineActivation, activation.id)
        assert service.operational_updated_at > row.heartbeat_deadline
        if timely:
            assert service.operational_status["first_heartbeat_at"] == first
        else:
            assert (
                datetime.fromisoformat(service.operational_status["first_heartbeat_at"])
                > row.heartbeat_deadline
            )
        controller = PipelineActivations(session)
        await controller.advance(activation.id)
        result = await controller.get(activation.id)
        assert result.phase == ("succeeded" if timely else "cancelling")


async def assert_failure_retained(writer, sessions, activation, snapshot):
    async with sessions() as session:
        service = await session.get(MonitoringService, activation.service_id)
        run = await session.get(PipelineRun, activation.run_id)
        assert service.operational_stage == run.status == "failed"
        assert run.ended_at is not None
        assert service.operational_status["pipeline_state"]["nodes"]["detector"] == {
            "state": "failed"
        }
    assert await writer.load_checkpoint(activation.service_id) == snapshot
    assert writer.total_errors == 0


@pytest.mark.asyncio
async def test_heartbeat_started_before_fatal_commit_cannot_replace_failed_status(
    signed_graph_writer, monkeypatch
):
    writer, sessions, activation, snapshot, _codec = signed_graph_writer
    captured, released = asyncio.Event(), asyncio.Event()
    original = writer._update_service_operational_status

    async def delayed_status(session, status):
        captured.set()
        await released.wait()
        await original(session, status)

    monkeypatch.setattr(writer, "_update_service_operational_status", delayed_status)
    heartbeat = asyncio.create_task(writer.write_heartbeat(healthy_metrics()))
    try:
        await asyncio.wait_for(captured.wait(), timeout=10)
        await writer.fail_pipeline_run(
            "Fatal after heartbeat capture",
            diagnostics={"nodes": {"detector": {"state": "failed"}}},
        )
        released.set()
        await asyncio.wait_for(heartbeat, timeout=10)
        await assert_failure_retained(writer, sessions, activation, snapshot)
    finally:
        released.set()
        await asyncio.gather(heartbeat, return_exceptions=True)


@pytest.mark.asyncio
async def test_fatal_waiting_for_inflight_status_publishes_last_without_deadlock(
    signed_graph_writer, monkeypatch
):
    writer, sessions, activation, snapshot, _codec = signed_graph_writer
    locked, released = asyncio.Event(), asyncio.Event()
    original = writer._can_publish_pipeline_status

    async def held_status_lock(session, service_id):
        result = await original(session, service_id)
        locked.set()
        await released.wait()
        return result

    monkeypatch.setattr(writer, "_can_publish_pipeline_status", held_status_lock)
    heartbeat = asyncio.create_task(writer.write_heartbeat(healthy_metrics()))
    failure = None
    try:
        await asyncio.wait_for(locked.wait(), timeout=10)
        failure = asyncio.create_task(
            writer.fail_pipeline_run(
                "Fatal while heartbeat owns status",
                diagnostics={"nodes": {"detector": {"state": "failed"}}},
            )
        )
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(failure), timeout=0.2)
        released.set()
        await asyncio.wait_for(heartbeat, timeout=10)
        await asyncio.wait_for(failure, timeout=10)
        await assert_failure_retained(writer, sessions, activation, snapshot)
    finally:
        released.set()
        await asyncio.gather(
            *(task for task in (heartbeat, failure) if task is not None),
            return_exceptions=True,
        )


@pytest.mark.asyncio
async def test_graph_heartbeat_remains_independent_of_blocked_checkpoint_commit(
    signed_graph_writer, monkeypatch
):
    writer, sessions, activation, snapshot, codec = signed_graph_writer
    replacement = codec.encode(codec.decode(snapshot))
    pending = asyncio.Event()
    original = writer._replace_checkpoint

    async def checkpoint_started(session, checkpoint):
        pending.set()
        await original(session, checkpoint)

    monkeypatch.setattr(writer, "_replace_checkpoint", checkpoint_started)
    commit = None
    async with sessions() as blocker:
        await blocker.execute(
            text(
                "SELECT service_id FROM radar_runtime_checkpoints "
                "WHERE service_id = :id FOR UPDATE"
            ),
            {"id": activation.service_id},
        )
        try:
            commit = asyncio.create_task(writer.commit_checkpoint(replacement))
            await asyncio.wait_for(pending.wait(), timeout=10)
            await asyncio.wait_for(writer.write_heartbeat(healthy_metrics()), timeout=5)
            assert not commit.done()
            assert writer.total_errors == 0
            async with sessions() as session:
                service = await session.get(MonitoringService, activation.service_id)
                assert service.operational_stage == "operational"
        finally:
            await blocker.rollback()
            if commit is not None:
                await asyncio.wait_for(commit, timeout=10)
    assert await writer.load_checkpoint(activation.service_id) == replacement
