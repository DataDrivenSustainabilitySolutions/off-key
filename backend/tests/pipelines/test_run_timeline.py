"""A run's timeline outlives its worker and explains how the run ended."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from aberration_core.db.models import (
    MonitoringService,
    PipelineActivation,
    PipelineRun,
    PipelineRunEvent,
)
from aberration_core.db.pipeline_locks import (
    complete_stopped_runs,
    lock_execution_records,
)
from aberration_core.db.run_events import (
    INSERT_RUN_EVENT,
    run_event,
    run_event_parameters,
)
from aberration_core.schemas.pipelines import MAX_TIMELINE_EVENTS
from aberration_tactic_middleware.domain import NotFoundError
from aberration_tactic_middleware.facades.docker import crashed_tasks
from aberration_tactic_middleware.services.orchestration.reconciliation import (
    RadarStatusReconciliationService,
)
from aberration_tactic_middleware.services.pipelines.activation import (
    PipelineActivations,
)
from aberration_tactic_middleware.services.pipelines.library import PipelineLibrary
from sqlalchemy import delete, func, select

from tests.support.signed_writer import healthy_metrics


async def timeline_of(sessions, service_id):
    async with sessions() as session:
        return await PipelineLibrary(session).timeline(service_id)


def steps(timeline):
    return [(event.source, event.kind, event.stage) for event in timeline.events]


async def bare_run(session, service_id):
    run = PipelineRun(
        id=str(uuid4()),
        service_id=service_id,
        execution=None,
        launch_config={},
        layout={},
        status="running",
    )
    session.add(run)
    await session.commit()
    return run


@pytest.mark.asyncio
async def test_heartbeat_stores_worker_events_after_the_setup_request(
    signed_graph_writer,
):
    writer, sessions, activation, _, _ = signed_graph_writer
    started = datetime.now(UTC)

    stored = await writer.write_heartbeat(
        {
            **healthy_metrics(),
            "run_events": [
                {
                    "kind": "runtime_started",
                    "stage": "starting",
                    "detail": {"restored_from_checkpoint": False},
                    "occurred_at": started,
                },
                {
                    "kind": "stage_changed",
                    "stage": "operational",
                    "detail": {"from": "starting", "threshold": float("nan")},
                    "occurred_at": started + timedelta(seconds=1),
                },
            ],
        }
    )

    assert stored is True
    timeline = await timeline_of(sessions, activation.service_id)
    assert steps(timeline) == [
        ("tactic", "activation_phase", "requested"),
        ("radar", "runtime_started", "starting"),
        ("radar", "stage_changed", "operational"),
    ]
    assert timeline.events[0].detail["revision_id"]
    # A non-finite value cannot reach JSON; it is stored as null.
    assert timeline.events[-1].detail == {"from": "starting", "threshold": None}
    assert timeline.status == "running" and not timeline.truncated


@pytest.mark.asyncio
async def test_events_wait_for_a_heartbeat_that_publishes_status(
    signed_graph_writer,
):
    writer, sessions, activation, _, _ = signed_graph_writer
    pending = [{"kind": "stage_changed", "stage": "operational", "detail": {}}]

    assert await writer.write_heartbeat({"run_events": pending}) is False
    assert await writer.write_heartbeat(healthy_metrics()) is True

    timeline = await timeline_of(sessions, activation.service_id)
    assert [event.source for event in timeline.events] == ["tactic"]


@pytest.mark.asyncio
async def test_failure_keeps_its_status_and_the_events_not_yet_sent(
    signed_graph_writer,
):
    writer, sessions, activation, _, _ = signed_graph_writer
    await writer.write_heartbeat(healthy_metrics())

    await writer.fail_pipeline_run(
        "Detector produced NaN",
        diagnostics={"nodes": {"detector": {"state": "failed"}}},
        events=[
            {
                "kind": "stage_changed",
                "stage": "degraded",
                "detail": {"detail": "Inference stalled"},
            }
        ],
    )
    async with sessions() as session:
        # Stopping the failed service later keeps the outcome it recorded.
        await lock_execution_records(session, [activation.service_id])
        await complete_stopped_runs(session, [activation.service_id])
        await session.commit()

    timeline = await timeline_of(sessions, activation.service_id)
    assert timeline.status == "failed"
    assert timeline.error == "Detector produced NaN"
    assert timeline.ended_at is not None
    assert timeline.final_status["stage"] == "failed"
    assert timeline.final_status["pipeline_state"]["nodes"]["detector"] == {
        "state": "failed"
    }
    # The failure already ended the run, so the stop adds no second ending.
    assert steps(timeline)[1:] == [
        ("radar", "stage_changed", "degraded"),
        ("radar", "run_failed", "failed"),
    ]
    assert timeline.events[-1].detail == {"error": "Detector produced NaN"}


@pytest.mark.asyncio
async def test_stopping_keeps_the_last_status_after_the_service_row_is_gone(
    signed_graph_writer,
):
    writer, sessions, activation, _, _ = signed_graph_writer
    await writer.write_heartbeat(healthy_metrics())

    async with sessions() as session:
        await lock_execution_records(session, [activation.service_id])
        await complete_stopped_runs(session, [activation.service_id])
        await session.commit()
        # Retention purge removes the service; the run and its timeline stay.
        await session.execute(
            delete(MonitoringService).where(
                MonitoringService.id == activation.service_id
            )
        )
        await session.commit()

    timeline = await timeline_of(sessions, activation.service_id)
    assert timeline.status == "stopped"
    assert timeline.final_status["stage"] == "operational"
    assert steps(timeline)[-1] == ("tactic", "run_ended", "stopped")
    assert timeline.events[-1].detail == {"status": "stopped"}


@pytest.mark.asyncio
async def test_setup_records_one_event_per_phase_it_reaches(signed_graph_writer):
    writer, sessions, activation, _, _ = signed_graph_writer
    await writer.write_heartbeat(healthy_metrics())
    async with sessions.begin() as session:
        row = await session.get(PipelineActivation, activation.id)
        row.phase = "awaiting_heartbeat"
        row.heartbeat_deadline = datetime.now(UTC) + timedelta(minutes=5)

    async with sessions() as session:
        controller = PipelineActivations(session)
        await controller.advance(activation.id)
        # A finished setup is not advanced again and adds nothing.
        await controller.advance(activation.id)

    timeline = await timeline_of(sessions, activation.service_id)
    setup = [event for event in timeline.events if event.kind.startswith("activation")]
    assert [(event.kind, event.stage) for event in setup] == [
        ("activation_phase", "requested"),
        ("activation_phase", "succeeded"),
    ]
    assert setup[-1].detail == {"from": "awaiting_heartbeat", "error": None}


@pytest.mark.asyncio
async def test_timeline_shows_the_newest_events_oldest_first(pipeline_database):
    async with pipeline_database() as session:
        run = await bare_run(session, "timeline-bounds")
        start = datetime(2026, 11, 3, tzinfo=UTC)
        # Insertion order differs from event time, which decides the order.
        session.add_all(
            run_event(
                run.id,
                "stage_changed",
                stage=str(index),
                occurred_at=start + timedelta(seconds=index),
            )
            for index in reversed(range(MAX_TIMELINE_EVENTS + 2))
        )
        await session.commit()
        library = PipelineLibrary(session)
        timeline = await library.timeline("timeline-bounds")
        with pytest.raises(NotFoundError):
            await library.timeline("no-such-service")

    assert timeline.truncated
    assert [event.stage for event in timeline.events] == [
        str(index) for index in range(2, MAX_TIMELINE_EVENTS + 2)
    ]


@pytest.mark.asyncio
async def test_worker_events_reach_only_their_own_run_and_stop_at_the_cap(
    pipeline_database,
):
    async with pipeline_database() as session:
        run = await bare_run(session, "capped")

        def worker_event(service_id):
            parameters = run_event_parameters(
                run_id=run.id, service_id=service_id, kind="probe", source="radar"
            )
            return {**parameters, "limit": 3}

        await session.execute(
            INSERT_RUN_EVENT, [worker_event("capped") for _ in range(5)]
        )
        # Another service's worker cannot write into this run.
        await session.execute(INSERT_RUN_EVENT, worker_event("someone-else"))
        await session.commit()
        stored = await session.scalar(
            select(func.count(PipelineRunEvent.id)).where(
                PipelineRunEvent.run_id == run.id
            )
        )
    assert stored == 3


def swarm_task(task_id, state, timestamp, **status):
    return {
        "ID": task_id,
        "NodeID": "node-1",
        "Status": {"State": state, "Timestamp": timestamp, **status},
    }


@pytest.mark.asyncio
async def test_each_crashed_task_is_recorded_once_oldest_first(pipeline_database):
    killed = swarm_task(
        "task-1",
        "failed",
        "2026-11-03T10:00:00Z",
        Err="task: non-zero exit (137)",
        ContainerStatus={"ExitCode": 137},
    )
    async with pipeline_database() as session:
        run = await bare_run(session, "crashing")
        record = RadarStatusReconciliationService._record_service_crashes
        await record(session, "crashing", crashed_tasks([killed]))
        await session.commit()
        later = swarm_task(
            "task-2", "rejected", "2026-11-03T10:05:00Z", Err="no suitable node"
        )
        await record(session, "crashing", crashed_tasks([killed, later]))
        await record(session, "unknown-service", crashed_tasks([later]))
        await session.commit()
        details = list(
            await session.scalars(
                select(PipelineRunEvent.detail)
                .where(PipelineRunEvent.run_id == run.id)
                .order_by(PipelineRunEvent.id)
            )
        )

    assert [detail["task_id"] for detail in details] == ["task-1", "task-2"]
    assert details[0]["exit_code"] == 137
    assert "memory limit" in details[0]["hint"]
    assert details[1]["error"] == "no suitable node"
