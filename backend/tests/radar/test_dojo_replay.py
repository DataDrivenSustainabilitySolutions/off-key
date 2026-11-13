"""Dojo replays: historical points through the live processing path."""

import asyncio
import json
import math
import threading
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from types import SimpleNamespace

import pytest
import pytest_asyncio
from off_key_core.db.models import (
    DojoDataset,
    DojoPoint,
    DojoRun,
    DojoRunResult,
    DojoSeries,
)
from off_key_core.models.dojo_runs import (
    BoundSeries,
    bind_dataset,
    calibration_comparison,
    series_topic,
)
from off_key_core.models.pipelines import compile_pipeline
from off_key_core.schemas.dojo import RunAlignment, RunSteps
from off_key_mqtt_radar import calibration_comparison as comparison_module
from off_key_mqtt_radar.dojo import worker as worker_module
from off_key_mqtt_radar.dojo.replay import (
    STEP_SAMPLES,
    Replay,
    ReplayResult,
    detection_config,
)
from off_key_mqtt_radar.dojo.settings import DojoWorkerSettings
from off_key_mqtt_radar.dojo.worker import (
    STALE_ERROR,
    DojoWorker,
    WorkerOptions,
    _Run,
    merged_points,
)
from sqlalchemy import func, select, update

from tests.support.pipelines import quick

START = datetime(2026, 3, 1, tzinfo=UTC)
# Above anything a test process holds. Past 80 % of its limit the processor
# collects garbage on every message, and a whole pytest session is larger than
# a worker: a worker-sized limit made each replay here take minutes.
MEMORY_LIMIT_MB = 16384


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
            execution(strategy, definition),
            alignment or RunAlignment(),
            MEMORY_LIMIT_MB,
        )
    )


def wave(index, slot):
    return math.sin(index / 7 + slot)


def test_default_design_seed_reproduces_adaptive_scores():
    def scores():
        run = replay()
        try:
            rows = []
            for index in range(250):
                for slot in range(3):
                    row = run.step(
                        series_topic(slot), START.timestamp() + index, wave(index, slot)
                    )
                    if row is not None and row.score is not None:
                        rows.append((row.score, row.alarm))
            return rows
        finally:
            run.close()

    first, second = scores(), scores()
    assert first
    assert first == second


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
    assert set(run.stats()) <= {"missing_reading", "waiting_for_reading"}


@pytest.mark.parametrize("strategy", ["adaptive_stream", "static_baseline"])
def test_a_replay_keeps_what_a_few_observations_looked_like_at_every_step(strategy):
    run = replay(strategy)
    rows = {}
    for index in range(400):
        for slot in range(3):
            row = run.step(
                series_topic(slot), START.timestamp() + index * 60, wave(index, slot)
            )
            if row is not None:
                rows[row.sequence] = (index, row)
    run.close()
    # Spread from the first result on, twice as far apart whenever they
    # would become twice as many as a run keeps.
    kept = [sample["sequence"] for sample in run.samples]
    assert STEP_SAMPLES <= len(kept) < 2 * STEP_SAMPLES
    assert kept[0] == 1 and kept == sorted(set(kept))
    assert max(b - a for a, b in pairwise(kept)) <= 2 * min(
        b - a for a, b in pairwise(kept)
    )
    assert kept[-1] > 400 - 2 * max(b - a for a, b in pairwise(kept))
    for sample in run.samples:
        index, row = rows[sample["sequence"]]
        assert sample["timestamp"] == row.timestamp.isoformat()
        assert sample["phase"] == row.phase
        # The readings as they went in, whatever the design did with them later.
        assert sample["steps"]["input"]["output"] == pytest.approx(
            {
                name: wave(index, slot)
                for slot, name in enumerate(("voltage", "current", "temperature"))
            }
        )
    learning, scored = run.samples[0]["steps"], run.samples[-1]["steps"]
    # Nothing is scored on the first observation, and the step says so.
    assert learning["detector"]["state"] == "not_executed"
    assert learning["detector"]["output"] is None and learning["detector"]["reason"]
    assert all(step["state"] == "ready" for step in scored.values())
    assert set(scored["scaler"]["input"]) == set(scored["scaler"]["output"])
    assert scored["scaler"]["input"] != scored["scaler"]["output"]
    assert isinstance(scored["detector"]["output"], float)
    # Small enough to keep beside the run's settings, and plain JSON.
    assert len(json.dumps(run.samples)) < 64 * 1024


def test_step_samples_are_thinned_until_they_fit_beside_the_settings(monkeypatch):
    samples = [{"sequence": index, "steps": {"x": "v" * 1000}} for index in range(20)]
    run = _Run("r", replay=SimpleNamespace(samples=samples))
    assert json.loads(run.observed()) == {"step_samples": samples}
    monkeypatch.setattr(worker_module, "MAX_SAMPLE_BYTES", 6000)
    kept = json.loads(run.observed())["step_samples"]
    assert [item["sequence"] for item in kept] == [0, 4, 8, 12, 16]
    monkeypatch.setattr(worker_module, "MAX_SAMPLE_BYTES", 500)
    assert run.observed() == "{}"
    assert _Run("r").observed() == "{}"


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


def test_readings_at_their_own_moments_form_one_observation_a_minute():
    run = replay()
    rows = []
    for index in range(50):
        stamp = (START + timedelta(minutes=index)).timestamp()
        for slot in range(3):
            # Each reading is 20 s after the previous one.
            row = run.step(series_topic(slot), stamp + 20 * slot, wave(index, slot))
            if row is not None:
                rows.append(row)
    run.close()
    # The last reading of each minute completes it, with nothing dropped. The
    # first minute spans 40 s, too long before any reading's interval is known.
    assert [row.timestamp for row in rows] == [
        START + timedelta(minutes=index, seconds=40) for index in range(1, 50)
    ]
    assert set(run.stats()) <= {"missing_reading", "waiting_for_reading"}


def test_a_reading_that_stops_drops_observations_once_its_value_is_too_old():
    run = replay(alignment=RunAlignment(hold_intervals=3))
    rows = []
    for index in range(20):
        stamp = (START + timedelta(minutes=index)).timestamp()
        for slot in range(3):
            # The third reading stops after ten minutes.
            if slot == 2 and index >= 10:
                continue
            row = run.step(series_topic(slot), stamp + slot, wave(index, slot))
            if row is not None:
                rows.append(row)
    run.close()
    # Its last value is held for three of its minutes, then each observation
    # that would use it is dropped and counted.
    assert len(rows) == 10 + 2
    assert run.stats()["stale_reading"] == 20 - 13


async def create_tables(engine):
    async with engine.begin() as connection:
        for table in (DojoDataset, DojoSeries, DojoPoint, DojoRun, DojoRunResult):
            await connection.run_sync(table.__table__.create)


@pytest_asyncio.fixture
async def dojo_engine(member_database):
    engine, sessions = member_database
    await create_tables(engine)
    return engine, sessions


async def seed(
    sessions, *, points=120, definition=None, status="queued", comparison=None
):
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
                    **({"calibration_comparison": comparison} if comparison else {}),
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
    # Stored with the run when it ends, in the shape the API reads back.
    steps = RunSteps(run_id=run.id, samples=run.config["step_samples"])
    assert STEP_SAMPLES <= len(steps.samples) < 2 * STEP_SAMPLES
    assert steps.samples[-1].steps["detector"].state == "ready"
    assert set(run.stats) <= {"missing_reading", "waiting_for_reading"}


@pytest.mark.asyncio
async def test_worker_stores_which_compared_methods_would_alarm(dojo_engine):
    engine, sessions = dojo_engine
    comparison = calibration_comparison(compile_pipeline(quick()))
    await seed(sessions, points=200, comparison=comparison)
    worker = DojoWorker(engine, WorkerOptions(worker_id="w1", write_batch=50))
    assert await worker.run_once() is True
    run, _ = await stored_run(sessions)
    assert run.status == "succeeded", run.error
    # Nothing failed, so the worker left the run's settings as they were.
    assert run.config["calibration_comparison"] == comparison
    async with sessions() as session:
        rows = (
            await session.execute(
                select(DojoRunResult.phase, DojoRunResult.method_alarms).order_by(
                    DojoRunResult.sequence
                )
            )
        ).all()
    judged = [mask for phase, mask in rows if phase == "operational"]
    # Every result after the calibration window is judged by all 15 methods.
    assert judged and all(mask is not None for mask in judged)
    assert all(0 <= mask < 1 << 15 for mask in judged)
    assert all(mask is None for phase, mask in rows if phase != "operational")


@pytest.mark.asyncio
async def test_worker_records_a_compared_method_that_failed(dojo_engine, monkeypatch):
    engine, sessions = dojo_engine
    comparison = {"own": "fixed_split", "methods": ["aci"], "alpha": 0.1}
    await seed(sessions, points=200, comparison={**comparison, "consecutive": 1})

    def broken(self, scores, value):
        raise ArithmeticError("no boundary")

    monkeypatch.setattr(comparison_module._Adapting, "exceeded", broken)
    worker = DojoWorker(engine, WorkerOptions(worker_id="w1"))
    assert await worker.run_once() is True
    run, results = await stored_run(sessions)
    # The run itself is untouched by a method that fails beside it.
    assert (run.status, results) == ("succeeded", 200)
    assert run.config["calibration_comparison"]["failed"] == {
        "aci": "ArithmeticError: no boundary"
    }
    assert run.config["calibration_comparison"]["methods"] == ["aci"]


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
    assert 0 <= run.points_read < 360 and results == run.result_count


@pytest.mark.asyncio
async def test_cancellation_committed_just_before_finish_wins(dojo_engine):
    engine, sessions = dojo_engine
    await seed(sessions, points=2)
    worker = DojoWorker(engine, WorkerOptions(worker_id="w1"))
    finish = worker._finish

    async def cancel_then_finish(run, status, error):
        async with sessions() as session:
            await session.execute(update(DojoRun).values(cancel_requested=True))
            await session.commit()
        await finish(run, status, error)

    worker._finish = cancel_then_finish
    await worker.run_once()
    run, results = await stored_run(sessions)
    assert run.status == "cancelled"
    assert run.result_count == results


def test_heartbeat_must_precede_expiration():
    with pytest.raises(ValueError, match="below"):
        DojoWorkerSettings(DOJO_HEARTBEAT_SECONDS=60, DOJO_STALE_SECONDS=30)
    with pytest.raises(ValueError, match="below"):
        WorkerOptions(worker_id="w", heartbeat_seconds=30, stale_seconds=30)


@pytest.mark.asyncio
async def test_fitting_keeps_heartbeating_while_another_replica_polls(
    dojo_engine, monkeypatch
):
    engine, sessions = dojo_engine
    await seed(sessions, points=2)
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def slow_step(*args):
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(15):
            raise RuntimeError("test did not release fitting")
        return

    monkeypatch.setattr(Replay, "step", slow_step)
    worker = DojoWorker(
        engine,
        WorkerOptions(worker_id="w1", heartbeat_seconds=1, stale_seconds=3),
    )
    task = asyncio.create_task(worker.run_once())
    try:
        await asyncio.wait_for(entered.wait(), 10)
        await asyncio.sleep(worker.options.stale_seconds + 0.5)
        other = DojoWorker(
            engine,
            WorkerOptions(worker_id="w2", heartbeat_seconds=1, stale_seconds=3),
        )
        assert not await other.run_once()
        run, _ = await stored_run(sessions)
        assert run.status == "running"
    finally:
        release.set()
        await task
    run, _ = await stored_run(sessions)
    assert run.status == "succeeded"


@pytest.mark.asyncio
@pytest.mark.parametrize("committed", [False, True])
async def test_flush_retains_results_until_commit_and_retries_idempotently(
    dojo_engine, committed
):
    engine, sessions = dojo_engine
    await seed(sessions, status="running")
    async with sessions() as session:
        await session.execute(update(DojoRun).values(worker="w1"))
        await session.commit()

    class FailedCommit:
        async def __aenter__(self):
            self.transaction = engine.begin()
            return await self.transaction.__aenter__()

        async def __aexit__(self, kind, value, trace):
            error = RuntimeError("commit response lost")
            if committed:
                await self.transaction.__aexit__(kind, value, trace)
            else:
                await self.transaction.__aexit__(RuntimeError, error, None)
            raise error

    worker = DojoWorker(
        SimpleNamespace(begin=FailedCommit), WorkerOptions(worker_id="w1")
    )
    run = _Run("run", pending=[ReplayResult(1, START, "ready", 0.1, None, False)])
    run.replay = SimpleNamespace(sequence=1, alarm_count=0, stats=dict)
    with pytest.raises(RuntimeError, match="commit response"):
        await worker._flush(run)
    assert len(run.pending) == 1
    worker.engine = engine
    await worker._flush(run)
    assert not run.pending
    stored, count = await stored_run(sessions)
    assert count == stored.result_count == 1


@pytest.mark.asyncio
async def test_slow_result_write_does_not_fail_its_own_heartbeat(
    dojo_engine, monkeypatch
):
    engine, sessions = dojo_engine
    await seed(sessions, status="running")
    async with sessions() as session:
        await session.execute(update(DojoRun).values(worker="w1"))
        await session.commit()
    worker = DojoWorker(
        engine,
        WorkerOptions(worker_id="w1", heartbeat_seconds=1, stale_seconds=3),
    )
    run = _Run("run", pending=[ReplayResult(1, START, "ready", 0.1, None, False)])
    run.replay = SimpleNamespace(sequence=1, alarm_count=0, stats=dict)
    entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    write = worker._write

    async def slow_write(connection, state):
        entered.set()
        await release.wait()
        return await write(connection, state)

    monkeypatch.setattr(worker, "_write", slow_write)
    flushing = asyncio.create_task(worker._flush(run))
    await asyncio.wait_for(entered.wait(), 10)
    heartbeat = asyncio.create_task(worker._keep_alive(run, finished))
    try:
        await asyncio.sleep(worker.options.stale_seconds + 0.5)
        assert run.heartbeat_error is None
    finally:
        release.set()
        await flushing
        finished.set()
        await heartbeat
    assert run.heartbeat_error is None
    assert not await DojoWorker(engine, worker.options).run_once()
    stored, count = await stored_run(sessions)
    assert stored.status == "running" and count == 1


@pytest.mark.asyncio
async def test_cancelled_initialization_closes_the_late_replay(
    dojo_engine, monkeypatch
):
    from off_key_mqtt_radar.dojo import worker as worker_module

    engine, sessions = dojo_engine
    await seed(sessions)
    entered, release, closed = asyncio.Event(), threading.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    def initialize(*_):
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(15):
            raise RuntimeError("test did not release initialization")
        return SimpleNamespace(close=closed.set)

    monkeypatch.setattr(worker_module, "Replay", initialize)
    task = asyncio.create_task(
        DojoWorker(engine, WorkerOptions(worker_id="w1")).run_once()
    )
    try:
        await asyncio.wait_for(entered.wait(), 10)
        task.cancel()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert closed.is_set()


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
