"""The fault-injection protocol: a grid of planted faults on a clean copy's
background, and a study scored against the clean copy and chance."""

import math
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from off_key_core.db.models import DojoDataset, DojoLabel, DojoRun, DojoRunResult
from off_key_core.schemas.dojo import (
    TEST_SEEDS,
    CsvImportQuery,
    FaultSuiteCreate,
    LabelCreate,
    StudyCreate,
)
from off_key_tactic_middleware.domain import ValidationError
from off_key_tactic_middleware.services.dojo import protocol
from off_key_tactic_middleware.services.dojo.datasets import DojoDatasets
from off_key_tactic_middleware.services.dojo.labels import DojoLabels
from off_key_tactic_middleware.services.dojo.suites import DojoSuites
from pydantic import ValidationError as SchemaError
from sqlalchemy import select

from tests.support.dojo import create_dojo_tables
from tests.support.env import set_auth_env
from tests.support.membership import bootstrap
from tests.support.pipelines import chained

T0 = datetime(2024, 1, 1, tzinfo=UTC)
VALUES = 1500
WARMUP = 200
WINDOW = 40


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


@pytest_asyncio.fixture
async def sessions(member_database, monkeypatch):
    set_auth_env(monkeypatch)
    engine, factory = member_database
    async with engine.begin() as connection:
        await connection.run_sync(create_dojo_tables)
    return factory


async def history(factory, values=VALUES):
    """A value a minute: a slow daily-like wave plus a small, repeating wobble,
    and one known problem at minute 900."""
    creator = await bootstrap(factory)
    rows = "\n".join(
        f"{at(i).isoformat()},{230 + 3 * math.sin(i / 90) + (i * 37 % 11) / 10:.4f}"
        for i in range(values)
    )
    async with factory() as session:
        view = await DojoDatasets(session).import_csv(
            f"time,voltage\n{rows}\n".encode(),
            CsvImportQuery(name="Charger"),
            created_by=creator,
        )
        if values > 905:
            await DojoLabels(session).create(
                view.id,
                LabelCreate(start_at=at(900), end_at=at(905), note="known trip"),
                created_by=creator,
            )
    return creator, view


async def screening(factory, view, creator, **fields):
    async with factory() as session:
        return await DojoSuites(session).create_fault_suite(
            FaultSuiteCreate(
                dataset_id=view.id,
                name="Screen",
                protocol="screening-v1",
                warmup_values=WARMUP,
                window_values=WINDOW,
                **fields,
            ),
            created_by=creator,
        )


async def sources(factory, suite):
    async with factory() as session:
        return [
            (await session.get(DojoDataset, item.dataset_id)).source
            for item in suite.items
        ]


@pytest.mark.asyncio
async def test_a_screening_suite_plants_one_fault_per_copy_after_warm_up(sessions):
    creator, view = await history(sessions)
    suite = await screening(sessions, view, creator, seed=3)
    found = await sources(sessions, suite)
    clean, faulted = found[0], found[1:]
    # One clean copy first, then a copy for every cell of the grid.
    assert clean["protocol"]["role"] == "clean" and clean["faults"] == []
    assert {item["protocol"]["cell"] for item in faulted} == {
        cell.id for cell in protocol.cells("screening-v1", 1)
    }
    assert len(faulted) == 48 and suite.datasets == 49
    manifest = clean["protocol"]
    assert (manifest["seed"], manifest["warmup_values"]) == (3, WARMUP)
    assert manifest["source_hash"] and manifest["untestable"] == []
    for item in faulted:
        (fault,) = item["faults"]
        start = datetime.fromisoformat(fault["start_at"])
        end = datetime.fromisoformat(fault["label_end"])
        # After the warm-up and a window, clear of the known problem by a window.
        assert start >= at(WARMUP + WINDOW)
        assert end < at(900 - WINDOW) or start > at(905 + WINDOW)
        assert fault["note"].startswith("Injected")
        assert isinstance(fault["simple_rules"], bool)
    # The sizes of one family share their places.
    steps = {
        item["faults"][0]["level"]: item["faults"][0]["start_at"]
        for item in faulted
        if item["protocol"]["cell"].startswith("step-")
        and item["protocol"]["cell"].endswith("-1")
    }
    assert len(steps) == 4 and len(set(steps.values())) == 1
    # Large sudden steps and impossible values are plain to the simple rules.
    by_cell = {item["protocol"]["cell"]: item["faults"][0] for item in faulted}
    assert by_cell["step-8-medium-1"]["simple_rules"]
    assert by_cell["out-of-range-medium-1"]["simple_rules"]
    # The same seed plants the same faults.
    again = await sources(sessions, await screening(sessions, view, creator, seed=3))
    assert [
        [(f["start_at"], f["kind"], f["sigmas"]) for f in item["faults"]]
        for item in again
    ] == [
        [(f["start_at"], f["kind"], f["sigmas"]) for f in item["faults"]]
        for item in found
    ]


@pytest.mark.asyncio
async def test_a_test_suite_draws_its_own_seed(sessions):
    creator, view = await history(sessions)
    suite = await screening(sessions, view, creator, purpose="test", seed=3)
    (clean, *_) = await sources(sessions, suite)
    assert clean["protocol"]["purpose"] == "test"
    assert clean["protocol"]["seed"] >= TEST_SEEDS
    assert "drawn by the server" in suite.description
    with pytest.raises(SchemaError, match="A test suite follows a protocol"):
        FaultSuiteCreate(dataset_id=view.id, name="x", purpose="test")


@pytest.mark.asyncio
async def test_a_history_too_short_for_any_fault_is_refused(sessions):
    creator, view = await history(sessions, values=300)
    with pytest.raises(ValidationError, match="No fault of screening-v1 fits"):
        await screening(sessions, view, creator)


async def finish(factory, run_id, alarm):
    """Let a run succeed with one result a minute after warm-up; ``alarm``
    decides from the minute and the copy's labels whether it alarms."""
    async with factory() as session:
        run = await session.get(DojoRun, run_id)
        labels = (
            await session.scalars(
                select(DojoLabel).where(DojoLabel.dataset_id == run.dataset_id)
            )
        ).all()
        dataset = await session.get(DojoDataset, run.dataset_id)
        last = round((dataset.end_at - T0).total_seconds() / 60)
        minutes = range(WARMUP, last + 1)
        flags = [alarm(minute, labels) for minute in minutes]
        run.status = "succeeded"
        run.result_count = len(minutes)
        run.alarm_count = sum(flags)
        run.points_read = run.points_total
        session.add_all(
            DojoRunResult(
                run_id=run_id,
                sequence=minute,
                timestamp=at(minute),
                phase="ready",
                score=1.0 if flag else 0.0,
                threshold=0.5,
                alarm=flag,
            )
            for minute, flag in zip(minutes, flags, strict=True)
        )
        await session.commit()


def planted(minute, labels):
    """Alarms inside every injected label and nowhere else."""
    return any(
        label.note.startswith("Injected")
        and label.start_at <= at(minute) <= label.end_at
        for label in labels
    )


async def studied(factory, suite, creator, alarm):
    async with factory() as session:
        study = await DojoSuites(session).create_study(
            StudyCreate(suite_id=suite.id, definition=chained(slots=("value",))),
            created_by=creator,
        )
    for item in study.items:
        await finish(factory, item.run_id, alarm)
    async with factory() as session:
        return await DojoSuites(session).get_study(study.id, calculate=True)


@pytest.mark.asyncio
async def test_a_study_is_scored_against_the_clean_copy_and_chance(sessions):
    creator, view = await history(sessions)
    suite = await screening(sessions, view, creator, seed=3)
    perfect = await studied(sessions, suite, creator, planted)
    report = perfect.protocol
    assert report is not None and report.within_budget
    assert report.false_alarms_per_day == 0 and report.alarm_share == 0
    assert report.caught == report.faults == 48
    assert report.adjusted_detection_rate == pytest.approx(1)
    step = next(item for item in report.families if item.family == "step")
    assert step.half == 1 and step.ninety == 1
    assert [level.caught for level in step.levels] == [2, 2, 2, 2]
    assert report.headline.startswith("0 false alarms a day")
    assert "simple rules catch" in report.headline
    # An alarm that never stops catches every fault and earns nothing for it.
    always = await studied(sessions, suite, creator, lambda minute, labels: True)
    report = always.protocol
    assert report is not None and report.within_budget is False
    assert report.alarm_share == 1
    # The clean copy alarms over every fault's span too: all are confounded.
    assert report.caught == 0
    assert all(
        level.confounded == level.faults
        for family in report.families
        for level in family.levels
    )


def test_wilson_monotone_and_crossing():
    low, high = protocol.wilson(2, 4) or (0, 0)
    assert low == pytest.approx(0.150, abs=1e-3)
    assert high == pytest.approx(0.850, abs=1e-3)
    assert protocol.wilson(0, 0) is None
    assert protocol.monotone([0.5, 0.0, 1.0, 1.0], [2, 2, 2, 2]) == [
        0.25,
        0.25,
        1.0,
        1.0,
    ]
    # Half way between 2σ (rate 0) and 4σ (rate 1) along log size: 2^1.5.
    assert protocol.crossing([1, 2, 4, 8], [0, 0, 1, 1], 0.5) == pytest.approx(2**1.5)
    assert protocol.crossing([1, 2], [0, 0.4], 0.5) is None


def test_simple_rules_see_large_jumps_repeats_and_silences():
    calm = [(float(i), 10 + (i % 3) / 10) for i in range(60)]
    jump = [(t, v + (5 if t >= 40 else 0)) for t, v in calm]
    assert protocol.simple_rules(jump, 40, 50, 0.1, 20)
    assert not protocol.simple_rules(calm, 40, 50, 0.1, 20)
    stuck = [(t, 7.0 if 40 <= t < 52 else v) for t, v in calm]
    assert protocol.simple_rules(stuck, 40, 52, None, 20)
    silent = [(t, v) for t, v in calm if not 40 <= t < 50]
    assert protocol.simple_rules(silent, 40, 50, None, 20)


@pytest.mark.asyncio
async def test_the_sizes_of_a_family_share_direction_and_noise(sessions):
    creator, view = await history(sessions)
    suite = await screening(sessions, view, creator, seed=5)
    group = {cell.id: cell.group for cell in protocol.cells("screening-v1", 1)}
    signs: dict = {}
    seeds: dict = {}
    for item in (await sources(sessions, suite))[1:]:
        (fault,) = item["faults"]
        key = group[item["protocol"]["cell"]]
        if fault["sigmas"] is not None:
            signs.setdefault(key, set()).add(math.copysign(1, fault["sigmas"]))
        if fault["kind"] == "noise":
            seeds.setdefault(key, set()).add(fault["seed"])
    assert signs and all(len(found) == 1 for found in signs.values())
    assert seeds and all(len(found) == 1 for found in seeds.values())
