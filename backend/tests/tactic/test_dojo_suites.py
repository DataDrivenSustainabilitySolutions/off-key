"""Benchmark suites and studies: fixed datasets, one design over all of them,
complete studies ranked and two studies compared dataset by dataset."""

import math
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from off_key_core.auth.agents import agent_key_digest, new_agent_key
from off_key_core.db.models import (
    Agent,
    DeploymentMaintenance,
    DojoDataset,
    DojoLabel,
    DojoPoint,
    DojoRun,
    DojoRunResult,
    DojoSeries,
    DojoStudy,
    DojoSuite,
    DojoSuiteDataset,
    MonitorEventRecord,
    PipelineProposal,
)
from off_key_core.schemas.dojo import (
    CsvImportQuery,
    LabelCreate,
    StudyComparisonQuery,
    StudyCreate,
    SuiteChange,
    SuiteCreate,
)
from off_key_tactic_middleware.domain import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from off_key_tactic_middleware.services.dojo.datasets import DojoDatasets
from off_key_tactic_middleware.services.dojo.labels import DojoLabels
from off_key_tactic_middleware.services.dojo.suites import DojoSuites, wilcoxon
from pydantic import ValidationError as SchemaError
from sqlalchemy import func, select

from tests.support.env import set_auth_env
from tests.support.membership import bootstrap
from tests.support.pipelines import chained, quick

T0 = datetime(2024, 1, 1, tzinfo=UTC)
MINUTES = 120


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


@pytest_asyncio.fixture
async def sessions(member_database, monkeypatch):
    set_auth_env(monkeypatch)
    engine, factory = member_database
    async with engine.begin() as connection:
        for table in (
            DeploymentMaintenance,
            Agent,
            DojoDataset,
            DojoSeries,
            DojoPoint,
            DojoLabel,
            DojoSuite,
            DojoSuiteDataset,
            DojoStudy,
            DojoRun,
            DojoRunResult,
            PipelineProposal,
            MonitorEventRecord,
        ):
            await connection.run_sync(table.__table__.create)
    return engine, factory


async def labelled(factory, creator, name, label_at, columns="x"):
    """A dataset of one value a minute with one label of five minutes."""
    width = len(columns.split(","))
    rows = "\n".join(
        f"{at(i).isoformat()}," + ",".join([str(i % 7)] * width) for i in range(MINUTES)
    )
    async with factory() as session:
        view = await DojoDatasets(session).import_csv(
            f"time,{columns}\n{rows}\n".encode(),
            CsvImportQuery(name=name),
            created_by=creator,
        )
        await DojoLabels(session).create(
            view.id,
            LabelCreate(start_at=at(label_at), end_at=at(label_at + 5)),
            created_by=creator,
        )
    return view


async def finish(factory, run_id, peak_at):
    """Let a queued run succeed with one score a minute, peaking at ``peak_at``."""
    async with factory() as session:
        run = await session.get(DojoRun, run_id)
        run.status = "succeeded"
        run.result_count = MINUTES - 10
        run.points_read = run.points_total
        session.add_all(
            DojoRunResult(
                run_id=run_id,
                sequence=minute,
                timestamp=at(minute),
                phase="ready",
                score=1.0 if peak_at <= minute <= peak_at + 5 else 0.1 + minute / 1000,
                threshold=None,
                alarm=peak_at <= minute <= peak_at + 5,
            )
            for minute in range(10, MINUTES)
        )
        await session.commit()


async def agent_named(factory, name):
    async with factory() as session:
        agent = Agent(
            name=name, key_hash=agent_key_digest(new_agent_key()), key_hint="abcd"
        )
        session.add(agent)
        await session.commit()
        return agent


def one_input():
    return chained(slots=("value",))


@pytest.mark.asyncio
async def test_a_study_runs_one_design_over_every_dataset_of_a_suite(sessions):
    _, factory = sessions
    creator = await bootstrap(factory)
    first = await labelled(factory, creator, "First", 50)
    second = await labelled(factory, creator, "Second", 80)
    async with factory() as session:
        suites = DojoSuites(session)
        suite = await suites.create_suite(
            SuiteCreate(name=" Two series ", dataset_ids=[second.id, first.id]),
            created_by=creator,
        )
        study = await suites.create_study(
            StudyCreate(suite_id=suite.id, definition=one_input(), name="MA"),
            created_by=creator,
        )
    assert (suite.name, suite.datasets, suite.reviewed) == ("Two series", 2, True)
    assert [item.name for item in suite.items] == ["Second", "First"]
    assert [item.labels for item in suite.items] == [1, 1]
    # One run per dataset, in the suite's order, each bound to its only series.
    assert [item.dataset_name for item in study.items] == ["Second", "First"]
    assert {item.status for item in study.items} == {"queued"}
    assert study.runs == {"queued": 2} and not study.complete
    async with factory() as session:
        runs = (
            await session.scalars(select(DojoRun).where(DojoRun.study_id == study.id))
        ).all()
    assert len(runs) == 2
    assert {run.config["series"][0]["name"] for run in runs} == {"x"}


@pytest.mark.asyncio
async def test_a_study_binds_series_by_name_or_queues_nothing(sessions):
    _, factory = sessions
    creator = await bootstrap(factory)
    wide = await labelled(factory, creator, "Wide", 50, columns="u,i,t")
    async with factory() as session:
        suites = DojoSuites(session)
        suite = await suites.create_suite(
            SuiteCreate(name="Wide", dataset_ids=[wide.id]), created_by=creator
        )
        with pytest.raises(ValidationError, match="'Wide' has no series for"):
            await suites.create_study(
                StudyCreate(suite_id=suite.id, definition=one_input()),
                created_by=creator,
            )
        with pytest.raises(ValidationError, match="no input 'nope'"):
            await suites.create_study(
                StudyCreate(
                    suite_id=suite.id, definition=one_input(), bindings={"nope": "u"}
                ),
                created_by=creator,
            )
        study = await suites.create_study(
            StudyCreate(
                suite_id=suite.id,
                definition=quick(),
                bindings={"voltage": "u", "current": "i", "temperature": "t"},
            ),
            created_by=creator,
        )
        queued = await session.scalar(select(func.count()).select_from(DojoRun))
    assert queued == 1 and study.bindings["voltage"] == "u"


@pytest.mark.asyncio
async def test_a_suites_datasets_never_change(sessions):
    _, factory = sessions
    creator = await bootstrap(factory)
    view = await labelled(factory, creator, "Kept", 50)
    with pytest.raises(SchemaError, match="only once"):
        SuiteCreate(name="Twice", dataset_ids=[view.id, view.id])
    async with factory() as session:
        suites = DojoSuites(session)
        suite = await suites.create_suite(
            SuiteCreate(name="Kept", dataset_ids=[view.id]), created_by=creator
        )
        renamed = await suites.change_suite(
            suite.id, SuiteChange(name="Renamed", description="Why")
        )
        with pytest.raises(NotFoundError):
            await suites.create_suite(
                SuiteCreate(name="Missing", dataset_ids=["nope"]), created_by=creator
            )
        with pytest.raises(ConflictError, match="benchmark suite 'Renamed'"):
            await DojoDatasets(session).remove(view.id)
    assert (renamed.name, renamed.description, renamed.datasets) == (
        "Renamed",
        "Why",
        1,
    )
    assert "dataset_ids" not in SuiteChange.model_fields


@pytest.mark.asyncio
async def test_complete_studies_are_ranked_and_compared_dataset_by_dataset(sessions):
    _, factory = sessions
    creator = await bootstrap(factory)
    views = [
        await labelled(factory, creator, f"Series {index}", 30 + 10 * index)
        for index in range(4)
    ]
    async with factory() as session:
        suites = DojoSuites(session)
        suite = await suites.create_suite(
            SuiteCreate(name="Four", dataset_ids=[view.id for view in views]),
            created_by=creator,
        )
        good = await suites.create_study(
            StudyCreate(suite_id=suite.id, definition=one_input(), name="Good"),
            created_by=creator,
        )
        poor = await suites.create_study(
            StudyCreate(suite_id=suite.id, definition=one_input(), name="Poor"),
            created_by=creator,
        )
        pending = await suites.create_study(
            StudyCreate(suite_id=suite.id, definition=one_input(), name="Pending"),
            created_by=creator,
        )
    for index, item in enumerate(good.items):
        await finish(factory, item.run_id, peak_at=30 + 10 * index)
    for item in poor.items:
        await finish(factory, item.run_id, peak_at=100)
    await finish(factory, pending.items[0].run_id, peak_at=30)
    async with factory() as session:
        suites = DojoSuites(session)
        before = await suites.get_suite(suite.id)
        read = await suites.get_study(good.id, calculate=True)
        await suites.get_study(poor.id, calculate=True)
        ranked = await suites.get_suite(suite.id)
        comparison = await suites.compare_studies(
            suite.id, StudyComparisonQuery(baseline=poor.id, challenger=good.id)
        )
    # Metrics come from reading a study; until then nothing is complete.
    assert before.leaderboard == [] and before.studies == 3
    assert read.metrics_pending == 0 and read.complete
    assert [item.dataset_name for item in read.items] == [view.name for view in views]
    assert read.totals.labels_detected == 4 and read.totals.detection_rate == 1.0
    assert read.totals.top1_hits == 4 and read.totals.top1_runs == 4
    assert [item.name for item in ranked.leaderboard] == ["Good", "Poor"]
    assert [item.name for item in ranked.unfinished] == ["Pending"]
    assert ranked.leaderboard[0].totals.vus_pr > ranked.leaderboard[1].totals.vus_pr
    assert (comparison.compared, comparison.wins, comparison.losses) == (4, 4, 0)
    assert comparison.mean_delta > 0
    # Four wins of four: the smallest exact two-sided p-value, 2 / 2**4.
    assert comparison.p_value == pytest.approx(0.125)
    assert [item.dataset_name for item in comparison.datasets] == [
        view.name for view in views
    ]


@pytest.mark.asyncio
async def test_studies_of_another_suite_are_not_compared(sessions):
    _, factory = sessions
    creator = await bootstrap(factory)
    view = await labelled(factory, creator, "One", 50)
    async with factory() as session:
        suites = DojoSuites(session)
        first = await suites.create_suite(
            SuiteCreate(name="First", dataset_ids=[view.id]), created_by=creator
        )
        second = await suites.create_suite(
            SuiteCreate(name="Second", dataset_ids=[view.id]), created_by=creator
        )
        mine = await suites.create_study(
            StudyCreate(suite_id=first.id, definition=one_input()), created_by=creator
        )
        theirs = await suites.create_study(
            StudyCreate(suite_id=second.id, definition=one_input()),
            created_by=creator,
        )
        with pytest.raises(ValidationError, match="one suite"):
            await suites.compare_studies(
                first.id, StudyComparisonQuery(baseline=mine.id, challenger=theirs.id)
            )


@pytest.mark.asyncio
async def test_a_keys_suite_waits_for_review_and_it_deletes_only_its_own(sessions):
    _, factory = sessions
    creator = await bootstrap(factory)
    view = await labelled(factory, creator, "Shared", 50)
    agent = await agent_named(factory, "scout")
    other = await agent_named(factory, "other")
    async with factory() as session:
        suites = DojoSuites(session)
        members = await suites.create_suite(
            SuiteCreate(name="Members", dataset_ids=[view.id]), created_by=creator
        )
        keys = await suites.create_suite(
            SuiteCreate(name="Keys", dataset_ids=[view.id]),
            created_by=None,
            created_by_agent=agent,
        )
        assert (keys.reviewed, keys.created_by_agent) == (False, "scout")
        study = await suites.create_study(
            StudyCreate(suite_id=members.id, definition=one_input()),
            created_by=None,
            created_by_agent=agent,
        )
        with pytest.raises(ForbiddenError):
            await suites.remove_suite(members.id, agent)
        with pytest.raises(ForbiddenError):
            await suites.change_suite(keys.id, SuiteChange(name="Mine"), other)
        with pytest.raises(ForbiddenError):
            await suites.cancel_study(study.id, other)
        reviewed = await suites.review_suite(keys.id, reviewed_by=creator)
        cancelled = await suites.cancel_study(study.id, agent)
        await suites.remove_study(study.id, agent)
        await suites.remove_suite(keys.id, agent)
        left = await session.scalar(select(func.count()).select_from(DojoRun))
    assert reviewed.reviewed
    assert cancelled.runs == {"cancelled": 1}
    assert left == 0


@pytest.mark.asyncio
async def test_a_running_study_is_cancelled_before_it_is_deleted(sessions):
    _, factory = sessions
    creator = await bootstrap(factory)
    view = await labelled(factory, creator, "Busy", 50)
    async with factory() as session:
        suites = DojoSuites(session)
        suite = await suites.create_suite(
            SuiteCreate(name="Busy", dataset_ids=[view.id]), created_by=creator
        )
        study = await suites.create_study(
            StudyCreate(suite_id=suite.id, definition=one_input()), created_by=creator
        )
        with pytest.raises(ConflictError, match="Cancel the study"):
            await suites.remove_suite(suite.id)
        await suites.cancel_study(study.id)
        with pytest.raises(ConflictError, match="No run"):
            await suites.cancel_study(study.id)
        await suites.remove_suite(suite.id)
        assert await session.get(DojoStudy, study.id) is None
        # The dataset is free again once its suite is gone.
        await DojoDatasets(session).remove(view.id)


@pytest.mark.asyncio
async def test_a_study_takes_one_place_in_the_queue(sessions, monkeypatch):
    from off_key_tactic_middleware.services.dojo import runs as runs_module

    monkeypatch.setattr(runs_module, "MAX_ACTIVE_RUNS", 2)
    _, factory = sessions
    creator = await bootstrap(factory)
    views = [await labelled(factory, creator, f"S{i}", 50) for i in range(3)]
    async with factory() as session:
        suites = DojoSuites(session)
        suite = await suites.create_suite(
            SuiteCreate(name="Three", dataset_ids=[view.id for view in views]),
            created_by=creator,
        )
        await suites.create_study(
            StudyCreate(suite_id=suite.id, definition=one_input()), created_by=creator
        )
        # Three queued runs, one place: a second study still fits.
        await suites.create_study(
            StudyCreate(suite_id=suite.id, definition=one_input()), created_by=creator
        )
        with pytest.raises(ConflictError, match="At most 2"):
            await suites.create_study(
                StudyCreate(suite_id=suite.id, definition=one_input()),
                created_by=creator,
            )


def test_wilcoxon_matches_the_exact_and_the_tied_distribution():
    assert wilcoxon([]) is None and wilcoxon([0.0, 0.1]) is None
    # Values checked against scipy.stats.wilcoxon.
    assert wilcoxon([0.1, 0.2, 0.3]) == pytest.approx(0.25)
    assert wilcoxon([0.3, -0.1, 0.2, 0.4, 0.5, 0.6]) == pytest.approx(0.0625)
    tied = wilcoxon([0.1, 0.1, -0.05, 0.2, 0.2, 0.3, -0.1, 0.05])
    assert tied == pytest.approx(0.07784, abs=1e-5)
    assert 0 < tied < 1 and not math.isnan(tied)
