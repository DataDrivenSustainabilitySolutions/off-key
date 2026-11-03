"""Actual signed-state writers serialize fatal status with stale heartbeats."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from off_key_core.db.models import MonitoringService, PipelineActivation, PipelineRun
from off_key_tactic_middleware.services.pipelines.activation import PipelineActivations
from sqlalchemy import text

from tests.support.signed_writer import healthy_metrics

pytestmark = pytest.mark.radar_integration


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
