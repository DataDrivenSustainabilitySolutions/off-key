"""Dojo replays: historical points through the live processing path."""

import math
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from off_key_core.db.models import (
    DojoDataset,
    DojoPoint,
    DojoRun,
    DojoRunResult,
    DojoSeries,
)
from off_key_core.models.dojo_runs import BoundSeries, bind_dataset, series_topic
from off_key_core.models.pipelines import compile_pipeline
from off_key_core.schemas.dojo import RunAlignment
from off_key_mqtt_radar.dojo.replay import Replay, detection_config
from off_key_mqtt_radar.dojo.worker import (
    STALE_ERROR,
    DojoWorker,
    WorkerOptions,
    merged_points,
)
from sqlalchemy import func, select, update

from tests.support.pipelines import quick

START = datetime(2026, 3, 1, tzinfo=UTC)


def execution(strategy="adaptive_stream", definition=None):
    definition = compile_pipeline(definition or quick(strategy)).definition
    return bind_dataset(
        definition,
        {
            slot.id: BoundSeries(
                id=f"series-{index}", position=index, name=slot.id, unit=None
            )
            for index, slot in enumerate(definition.input_slots)
        },
        run_id="run",
    )


def replay(strategy="adaptive_stream", alignment=None, definition=None):
    return Replay(
        detection_config(
            execution(strategy, definition), alignment or RunAlignment(), 512
        )
    )


def wave(index, slot):
    return math.sin(index / 7 + slot)


@pytest.mark.parametrize("strategy", ["adaptive_stream", "static_baseline"])
def test_years_old_minute_data_is_scored_like_live_input(strategy):
    """Wall-clock limits would reject all of it; the replay clock accepts it."""
    run = replay(strategy)
    rows = []
    for index in range(400):
        stamp = (START + timedelta(minutes=index)).timestamp()
        for slot in range(3):
            row = run.step(series_topic(slot), stamp, wave(index, slot))
            if row is not None:
                rows.append(row)
    run.close()
    # One aligned observation per minute, numbered in order.
    assert [row.sequence for row in rows] == list(range(1, 401))
    assert rows[-1].timestamp == START + timedelta(minutes=399)
    scored = [row for row in rows if row.score is not None]
    assert scored and all(math.isfinite(row.score) for row in scored)
    # The two readings that arrive first each minute wait for the third.
    assert set(run.stats()) <= {"stale_sensor_block", "waiting_for_all"}


def test_static_baseline_discards_nothing_while_it_fits():
    run = replay("static_baseline")
    phases = []
    for index in range(300):
        stamp = (START + timedelta(minutes=index)).timestamp()
        for slot in range(3):
            row = run.step(series_topic(slot), stamp, wave(index, slot))
            if row is not None:
                phases.append(row.phase)
    run.close()
    assert "training_discarded" not in phases
    assert phases[-1] == "ready"


def test_readings_further_apart_than_the_skew_never_combine():
    run = replay(alignment=RunAlignment(freshness_seconds=600, max_skew_seconds=5))
    for index in range(50):
        stamp = (START + timedelta(minutes=index)).timestamp()
        for slot in range(3):
            # Each reading is 20 s after the previous one.
            assert run.step(series_topic(slot), stamp + 20 * slot, 1.0) is None
    run.close()
    assert run.stats()["observation_skew_block"] > 0


async def create_tables(engine):
    async with engine.begin() as connection:
        for table in (DojoDataset, DojoSeries, DojoPoint, DojoRun, DojoRunResult):
            await connection.run_sync(table.__table__.create)


@pytest_asyncio.fixture
async def dojo_engine(member_database):
    engine, sessions = member_database
    await create_tables(engine)
    return engine, sessions


async def seed(sessions, *, points=120, definition=None, status="queued"):
    bound = execution(definition=definition)
    async with sessions() as session:
        session.add(
            DojoDataset(
                id="d",
                name="Trip",
                description="",
                origin="csv",
                source={},
                point_count=points * len(bound.bindings),
            )
        )
        for index, binding in enumerate(bound.bindings):
            session.add(
                DojoSeries(
                    id=binding.reading_id,
                    dataset_id="d",
                    position=index,
                    name=binding.slot_id,
                    point_count=points,
                )
            )
        await session.flush()
        session.add_all(
            DojoPoint(
                series_id=binding.reading_id,
                timestamp=START + timedelta(minutes=minute),
                value=wave(minute, index),
            )
            for index, binding in enumerate(bound.bindings)
            for minute in range(points)
        )
        session.add(
            DojoRun(
                id="run",
                dataset_id="d",
                name="",
                status=status,
                config={
                    "execution": bound.model_dump(mode="json"),
                    "alignment": RunAlignment().model_dump(mode="json"),
                    "series": [
                        {"id": item.reading_id, "topic": item.accepted_topic}
                        for item in bound.bindings
                    ],
                },
                cancel_requested=False,
                points_total=points * len(bound.bindings),
                points_read=0,
                result_count=0,
                alarm_count=0,
                stats={},
            )
        )
        await session.commit()


async def stored_run(sessions):
    async with sessions() as session:
        run = await session.get(DojoRun, "run")
        results = await session.scalar(select(func.count()).select_from(DojoRunResult))
        return run, results


@pytest.mark.asyncio
async def test_merged_points_interleave_series_in_time_order(dojo_engine):
    engine, sessions = dojo_engine
    await seed(sessions, points=7)
    series = [{"id": f"series-{index}", "topic": f"t{index}"} for index in range(3)]
    points = [item async for item in merged_points(engine, series, batch=2)]
    assert len(points) == 21
    assert points[:3] == [
        ("t0", START.timestamp(), wave(0, 0)),
        ("t1", START.timestamp(), wave(0, 1)),
        ("t2", START.timestamp(), wave(0, 2)),
    ]
    assert [stamp for _, stamp, _ in points] == sorted(stamp for _, stamp, _ in points)


@pytest.mark.asyncio
async def test_worker_replays_a_queued_run_and_stores_its_results(dojo_engine):
    engine, sessions = dojo_engine
    await seed(sessions)
    worker = DojoWorker(engine, WorkerOptions(worker_id="w1", write_batch=50))
    assert await worker.run_once() is True
    assert await worker.run_once() is False
    run, results = await stored_run(sessions)
    assert run.status == "succeeded", run.error
    assert (run.points_read, run.result_count, results) == (360, 120, 120)
    assert run.worker == "w1" and run.finished_at is not None
    assert set(run.stats) <= {"stale_sensor_block", "waiting_for_all"}


@pytest.mark.asyncio
async def test_a_cancelled_run_stops_at_the_next_heartbeat(dojo_engine):
    engine, sessions = dojo_engine
    await seed(sessions)
    async with sessions() as session:
        await session.execute(update(DojoRun).values(cancel_requested=True))
        await session.commit()
    worker = DojoWorker(engine, WorkerOptions(worker_id="w1", write_batch=10))
    await worker.run_once()
    run, results = await stored_run(sessions)
    assert run.status == "cancelled"
    assert 0 < run.points_read < 360 and results == run.result_count


@pytest.mark.asyncio
async def test_a_stopping_worker_puts_its_run_back_in_the_queue(dojo_engine):
    engine, sessions = dojo_engine
    await seed(sessions)
    calls = iter(range(10_000))
    worker = DojoWorker(
        engine,
        WorkerOptions(worker_id="w1", write_batch=10),
        should_stop=lambda: next(calls) > 100,
    )
    await worker.run_once()
    run, results = await stored_run(sessions)
    assert (run.status, run.worker, run.points_read, results) == ("queued", None, 0, 0)


@pytest.mark.asyncio
async def test_a_design_that_cannot_run_fails_with_its_reason(dojo_engine):
    engine, sessions = dojo_engine
    await seed(sessions)
    async with sessions() as session:
        run = await session.get(DojoRun, "run")
        run.config = {**run.config, "execution": {"definition": {}}}
        await session.commit()
    await DojoWorker(engine, WorkerOptions(worker_id="w1")).run_once()
    run, _ = await stored_run(sessions)
    assert run.status == "failed" and run.error


@pytest.mark.asyncio
async def test_a_run_whose_worker_vanished_is_failed_by_the_next_poll(dojo_engine):
    engine, sessions = dojo_engine
    await seed(sessions, status="running")
    async with sessions() as session:
        await session.execute(
            update(DojoRun).values(
                worker="gone", heartbeat_at=datetime.now(UTC) - timedelta(minutes=5)
            )
        )
        await session.commit()
    assert await DojoWorker(engine, WorkerOptions(worker_id="w1")).run_once() is False
    run, _ = await stored_run(sessions)
    assert (run.status, run.error) == ("failed", STALE_ERROR)
