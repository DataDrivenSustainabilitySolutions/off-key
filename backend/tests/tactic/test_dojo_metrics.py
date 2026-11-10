"""Dojo labels and event metrics: labels as events, alarms scored against them."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from off_key_core.db.base import get_db_async
from off_key_core.db.models import (
    DeploymentMaintenance,
    DojoDataset,
    DojoLabel,
    DojoPoint,
    DojoRun,
    DojoRunResult,
    DojoSeries,
    User,
)
from off_key_core.schemas.dojo import (
    MAX_COMPARED_RUNS,
    ComparisonQuery,
    CsvImportQuery,
    LabelChange,
    LabelCreate,
    RunResultsQuery,
)
from off_key_tactic_middleware.api.v1.dojo import router
from off_key_tactic_middleware.domain import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from off_key_tactic_middleware.services.dojo import labels as labels_module
from off_key_tactic_middleware.services.dojo.datasets import DojoDatasets
from off_key_tactic_middleware.services.dojo.labels import DojoLabels
from off_key_tactic_middleware.services.dojo.metrics import (
    Alarm,
    DojoMetrics,
    Interval,
    evaluate,
)
from off_key_tactic_middleware.services.dojo.runs import DojoRuns
from pydantic import ValidationError as SchemaError
from sqlalchemy import func, select

from tests.support.env import set_auth_env
from tests.support.http import asgi_client
from tests.support.membership import bootstrap
from tests.support.tokens import access_token

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def alarms(*minutes: float) -> list[Alarm]:
    """Alarm rows at whole minutes; consecutive minutes continue one alarm."""
    return [
        Alarm(at(minute), onset=index == 0 or minutes[index - 1] != minute - 1)
        for index, minute in enumerate(minutes)
    ]


# --- evaluation ---------------------------------------------------------------


def test_a_label_is_detected_by_its_first_alarm_and_missed_without_one():
    labels = [Interval("a", at(10), at(20)), Interval("b", at(40), at(50))]
    result = evaluate(labels, alarms(14, 15, 16), at(0), at(100))
    assert [(item.outcome, item.delay_seconds) for item in result.labels] == [
        ("detected", 240.0),
        ("missed", None),
    ]
    assert result.labels[0].first_alarm_at == at(14)
    assert (result.labels_scored, result.labels_detected) == (2, 1)
    assert (result.false_alarms, result.evaluated_seconds) == (0, 80 * 60.0)


def test_label_ends_count_as_inside():
    labels = [Interval("a", at(10), at(20)), Interval("b", at(20), at(30))]
    result = evaluate(labels, alarms(10) + alarms(30), at(0), at(60))
    assert [item.delay_seconds for item in result.labels] == [0.0, 600.0]
    assert result.false_alarms == 0


def test_false_alarms_count_onsets_outside_labels_once():
    labels = [Interval("a", at(10), at(20))]
    # Two alarms outside (one held for three results), one alarm that starts
    # in the label and outlasts it, which is not a false alarm.
    result = evaluate(labels, alarms(2, 3, 4, 7, 19, 20, 21, 22), at(0), at(60))
    assert result.false_alarms == 2
    assert result.labels[0].first_alarm_at == at(19)


def test_an_alarm_held_into_a_label_detects_it():
    labels = [Interval("a", at(10), at(20))]
    result = evaluate(labels, alarms(8, 9, 10, 11), at(0), at(60))
    assert result.labels[0].outcome == "detected"
    assert result.labels[0].delay_seconds == 0.0
    assert result.false_alarms == 1


def test_labels_without_scores_are_unscored_and_leave_the_rate_out():
    labels = [
        Interval("learning", at(0), at(5)),
        Interval("scored", at(30), at(40)),
        Interval("after", at(200), at(210)),
    ]
    result = evaluate(labels, [], at(10), at(100))
    assert [item.outcome for item in result.labels] == [
        "unscored",
        "missed",
        "unscored",
    ]
    assert result.labels_scored == 1
    assert result.evaluated_seconds == (90 - 10) * 60.0


def test_a_run_without_scores_evaluates_nothing():
    result = evaluate([Interval("a", at(0), at(5))], [], None, None)
    assert result.labels[0].outcome == "unscored"
    assert (result.labels_scored, result.evaluated_seconds) == (0, 0.0)


# --- labels and metrics in the database ---------------------------------------


@pytest_asyncio.fixture
async def sessions(member_database, monkeypatch):
    set_auth_env(monkeypatch)
    engine, factory = member_database
    async with engine.begin() as connection:
        for table in (
            DeploymentMaintenance,
            DojoDataset,
            DojoSeries,
            DojoPoint,
            DojoLabel,
            DojoRun,
            DojoRunResult,
        ):
            await connection.run_sync(table.__table__.create)
    return engine, factory


async def dataset(factory, minutes=120):
    creator = await bootstrap(factory)
    rows = "\n".join(f"{at(i).isoformat()},{i % 7}" for i in range(minutes))
    async with factory() as session:
        view = await DojoDatasets(session).import_csv(
            f"time,u\n{rows}\n".encode(),
            CsvImportQuery(name="Trips"),
            created_by=creator,
        )
    return creator, view


async def finished_run(factory, view, *, alarm_minutes, name="", status="succeeded"):
    """A run as the worker leaves it: learning for 10 minutes, then scoring."""
    run_id = f"run-{name or 'x'}"
    async with factory() as session:
        session.add(
            DojoRun(
                id=run_id,
                dataset_id=view.id,
                name=name,
                status=status,
                config={"execution": {"definition": {"strategy": "static_baseline"}}},
                cancel_requested=False,
                points_total=120,
                points_read=120,
                result_count=120,
                alarm_count=len(alarm_minutes),
                stats={},
            )
        )
        session.add_all(
            DojoRunResult(
                run_id=run_id,
                sequence=minute + 1,
                timestamp=at(minute),
                phase="collecting" if minute < 10 else "ready",
                score=None if minute < 10 else 0.5,
                threshold=None,
                alarm=minute in alarm_minutes,
            )
            for minute in range(120)
        )
        await session.commit()
    return run_id


def label(start, end, note=""):
    return LabelCreate(start_at=at(start), end_at=at(end), note=note)


@pytest.mark.asyncio
async def test_labels_are_kept_in_order_and_may_touch_but_not_overlap(sessions):
    _, factory = sessions
    creator, view = await dataset(factory)
    async with factory() as session:
        service = DojoLabels(session)
        late = await service.create(
            view.id, label(60, 70, " pump "), created_by=creator
        )
        early = await service.create(view.id, label(20, 30), created_by=creator)
        await service.create(view.id, label(30, 40), created_by=creator)
        with pytest.raises(ConflictError, match="may not overlap"):
            await service.create(view.id, label(25, 35), created_by=creator)
        with pytest.raises(ConflictError, match="may not overlap"):
            await service.change(view.id, early.id, LabelChange(end_at=at(65)))
        moved = await service.change(
            view.id, late.id, LabelChange(start_at=at(50), note="valve")
        )
        with pytest.raises(ValidationError, match="end_at must be after"):
            await service.change(view.id, late.id, LabelChange(end_at=at(45)))
        listed = await service.list(view.id)
    assert late.note == "pump" and late.created_by == creator
    assert (moved.start_at, moved.end_at, moved.note) == (at(50), at(70), "valve")
    assert [item.start_at for item in listed.items] == [at(20), at(30), at(50)]


@pytest.mark.asyncio
async def test_labels_must_touch_the_dataset_and_have_a_valid_interval(sessions):
    _, factory = sessions
    creator, view = await dataset(factory)
    async with factory() as session:
        service = DojoLabels(session)
        with pytest.raises(ValidationError, match="outside the dataset"):
            await service.create(view.id, label(500, 510), created_by=creator)
        with pytest.raises(NotFoundError, match="Dataset not found"):
            await service.create("missing", label(1, 2), created_by=creator)
        with pytest.raises(NotFoundError, match="Label not found"):
            await service.remove(view.id, "missing")
    with pytest.raises(SchemaError, match="end_at must be after"):
        label(10, 10)
    with pytest.raises(SchemaError, match="time zone"):
        LabelCreate(start_at=datetime(2024, 1, 1), end_at=at(10))


@pytest.mark.asyncio
async def test_a_dataset_holds_a_bounded_number_of_labels(sessions, monkeypatch):
    _, factory = sessions
    creator, view = await dataset(factory)
    monkeypatch.setattr(labels_module, "MAX_DATASET_LABELS", 1)
    async with factory() as session:
        service = DojoLabels(session)
        await service.create(view.id, label(1, 2), created_by=creator)
        with pytest.raises(ConflictError, match="at most 1 labels"):
            await service.create(view.id, label(3, 4), created_by=creator)


@pytest.mark.asyncio
async def test_metrics_score_a_finished_run_against_the_current_labels(sessions):
    _, factory = sessions
    creator, view = await dataset(factory)
    run_id = await finished_run(factory, view, alarm_minutes={5, 33, 34, 80, 81})
    async with factory() as session:
        labels = DojoLabels(session)
        problem = await labels.create(view.id, label(30, 40), created_by=creator)
        learning = await labels.create(view.id, label(0, 8), created_by=creator)
        quiet = await labels.create(view.id, label(100, 110), created_by=creator)
        metrics = await DojoMetrics(session).run(run_id)
        await labels.change(view.id, quiet.id, LabelChange(start_at=at(78)))
        rescored = await DojoMetrics(session).run(run_id)
    assert [(item.label_id, item.outcome) for item in metrics.labels] == [
        (learning.id, "detected"),
        (problem.id, "detected"),
        (quiet.id, "missed"),
    ]
    assert (metrics.scored_from, metrics.scored_to) == (at(10), at(119))
    assert (metrics.labels_total, metrics.labels_scored) == (3, 3)
    assert metrics.labels_detected == 2
    assert metrics.median_delay_seconds == 240.0
    assert metrics.max_delay_seconds == 300.0
    assert metrics.alarm_count == 5
    # The alarm at minute 80 is the only onset outside every label; scored
    # time outside labels is 109 minutes less the 10 inside 30-40 and 100-110.
    assert metrics.false_alarms == 1
    assert metrics.evaluated_seconds == (109 - 20) * 60.0
    assert metrics.false_alarms_per_day == pytest.approx(86_400 / (89 * 60))
    assert metrics.strategy == "static_baseline"
    # Moving a label re-scores the run: the alarm at 80 now detects it.
    assert rescored.false_alarms == 0 and rescored.labels_detected == 3


@pytest.mark.asyncio
async def test_a_comparison_puts_runs_of_one_dataset_side_by_side(sessions):
    _, factory = sessions
    creator, view = await dataset(factory)
    _, other = await dataset_of(factory, creator)
    eager = await finished_run(factory, view, alarm_minutes={31, 60}, name="eager")
    calm = await finished_run(factory, view, alarm_minutes=set(), name="calm")
    busy = await finished_run(
        factory, view, alarm_minutes=set(), name="busy", status="running"
    )
    foreign = await finished_run(factory, other, alarm_minutes=set(), name="foreign")
    async with factory() as session:
        await DojoLabels(session).create(view.id, label(30, 40), created_by=creator)
        service = DojoMetrics(session)
        comparison = await service.compare(
            view.id, ComparisonQuery(run_ids=[eager, calm])
        )
        with pytest.raises(ValidationError, match="ran on another"):
            await service.compare(view.id, ComparisonQuery(run_ids=[eager, foreign]))
        with pytest.raises(ConflictError, match="is running"):
            await service.compare(view.id, ComparisonQuery(run_ids=[busy]))
        with pytest.raises(NotFoundError, match="Run not found"):
            await service.run("missing")
    assert [item.run_name for item in comparison.runs] == ["eager", "calm"]
    assert [item.detection_rate for item in comparison.runs] == [1.0, 0.0]
    assert [item.false_alarms for item in comparison.runs] == [1, 0]
    assert [item.start_at for item in comparison.labels] == [at(30)]
    with pytest.raises(SchemaError, match="only once"):
        ComparisonQuery(run_ids=[eager, eager])
    ids = [f"r{index}" for index in range(MAX_COMPARED_RUNS)]
    assert ComparisonQuery(run_ids=ids).run_ids == ids
    with pytest.raises(SchemaError, match=f"at most {MAX_COMPARED_RUNS}"):
        ComparisonQuery(run_ids=[*ids, "one more"])


async def dataset_of(factory, creator):
    async with factory() as session:
        view = await DojoDatasets(session).import_csv(
            f"time,u\n{at(0).isoformat()},1\n{at(1).isoformat()},2\n".encode(),
            CsvImportQuery(name="Other"),
            created_by=creator,
        )
    return creator, view


@pytest.mark.asyncio
async def test_results_can_be_read_as_alarms_only(sessions):
    _, factory = sessions
    _, view = await dataset(factory)
    run_id = await finished_run(factory, view, alarm_minutes={12, 40, 41})
    async with factory() as session:
        service = DojoRuns(session)
        first = await service.results(run_id, RunResultsQuery(alarm=True, limit=2))
        rest = await service.results(
            run_id, RunResultsQuery(alarm=True, after=first.next_after)
        )
    assert [item.timestamp for item in first.items + rest.items] == [
        at(12),
        at(40),
        at(41),
    ]
    assert rest.next_after is None


@pytest.mark.asyncio
async def test_deleting_a_dataset_removes_its_labels(sessions):
    _, factory = sessions
    creator, view = await dataset(factory)
    async with factory() as session:
        await DojoLabels(session).create(view.id, label(1, 2), created_by=creator)
        await DojoDatasets(session).remove(view.id)
        remaining = await session.scalar(select(func.count()).select_from(DojoLabel))
    assert remaining == 0


def app(factory):
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")

    async def database():
        async with factory() as session:
            yield session

    application.dependency_overrides[get_db_async] = database
    return application


@pytest.mark.asyncio
async def test_routes_label_a_dataset_and_compare_runs(sessions):
    _, factory = sessions
    creator, view = await dataset(factory)
    run_id = await finished_run(factory, view, alarm_minutes={35})
    async with factory() as session:
        admin = await session.get(User, creator)
    headers = {"Authorization": f"Bearer {access_token(admin)}"}
    base = f"/api/v1/dojo/datasets/{view.id}"
    async with asgi_client(app(factory)) as client:
        created = await client.post(
            f"{base}/labels",
            json={"start_at": at(30).isoformat(), "end_at": at(40).isoformat()},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        label_id = created.json()["id"]
        changed = await client.patch(
            f"{base}/labels/{label_id}", json={"note": "fault"}, headers=headers
        )
        listed = await client.get(f"{base}/labels", headers=headers)
        metrics = await client.get(
            f"/api/v1/dojo/runs/{run_id}/metrics", headers=headers
        )
        compared = await client.get(
            f"{base}/comparison", params={"run_ids": [run_id]}, headers=headers
        )
        too_many = await client.get(
            f"{base}/comparison",
            params={"run_ids": [f"r{index}" for index in range(MAX_COMPARED_RUNS + 1)]},
            headers=headers,
        )
        overlapping = await client.post(
            f"{base}/labels",
            json={"start_at": at(35).isoformat(), "end_at": at(45).isoformat()},
            headers=headers,
        )
        deleted = await client.delete(f"{base}/labels/{label_id}", headers=headers)
        anonymous = await client.get(f"{base}/labels")
    assert changed.json()["note"] == "fault"
    assert [item["id"] for item in listed.json()["items"]] == [label_id]
    assert metrics.json()["labels"][0]["outcome"] == "detected"
    assert metrics.json()["labels"][0]["delay_seconds"] == 300.0
    assert compared.status_code == 200, compared.text
    assert [item["run_id"] for item in compared.json()["runs"]] == [run_id]
    assert too_many.status_code == 422
    assert overlapping.status_code == 409
    assert deleted.status_code == 204
    assert anonymous.status_code == 401
