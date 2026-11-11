"""Dojo runs: bound at creation, replayed by the worker, read back in pages."""

import asyncio
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
from off_key_core.models.pipeline_calibration import CALIBRATORS
from off_key_core.schemas.dojo import (
    CsvImportQuery,
    RunAlignment,
    RunCreate,
    RunListQuery,
    RunResultsQuery,
)
from off_key_mqtt_radar.dojo.worker import DojoWorker, WorkerOptions
from off_key_tactic_middleware.api.v1.dojo import router
from off_key_tactic_middleware.domain import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from off_key_tactic_middleware.services.dojo import runs as runs_module
from off_key_tactic_middleware.services.dojo.datasets import DojoDatasets
from off_key_tactic_middleware.services.dojo.metrics import DojoMetrics
from off_key_tactic_middleware.services.dojo.runs import DojoRuns
from sqlalchemy import func, select

from tests.support.env import set_auth_env
from tests.support.http import asgi_client
from tests.support.membership import bootstrap
from tests.support.pipelines import quick
from tests.support.tokens import access_token

T0 = datetime(2024, 1, 1, tzinfo=UTC)
SLOTS = ("voltage", "current", "temperature")


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


async def dataset(factory, minutes=200):
    creator = await bootstrap(factory)
    rows = "\n".join(
        f"{(T0 + timedelta(minutes=i)).isoformat()},{i % 7},{i % 5},{20 + i % 3}"
        for i in range(minutes)
    )
    async with factory() as session:
        view = await DojoDatasets(session).import_csv(
            f"time,u,i,t\n{rows}\n".encode(),
            CsvImportQuery(name="Old trips"),
            created_by=creator,
        )
    return creator, view


def request(view, **fields):
    fields.setdefault("definition", quick())
    return RunCreate(
        dataset_id=view.id,
        bindings={
            slot: series.id for slot, series in zip(SLOTS, view.series, strict=True)
        },
        **fields,
    )


@pytest.mark.asyncio
async def test_a_run_is_bound_queued_replayed_and_read_back(sessions):
    engine, factory = sessions
    creator, view = await dataset(factory)
    async with factory() as session:
        run = await DojoRuns(session).create(
            request(view, name=" iForest "), created_by=creator
        )
    assert (run.status, run.name, run.strategy) == (
        "queued",
        "iForest",
        "adaptive_stream",
    )
    assert run.points_total == 600
    assert [(item.slot_id, item.series_name) for item in run.bindings] == [
        ("voltage", "u"),
        ("current", "i"),
        ("temperature", "t"),
    ]
    assert run.alignment == RunAlignment()

    worker = DojoWorker(engine, WorkerOptions(worker_id="w", write_batch=40))
    assert await worker.run_once()

    async with factory() as session:
        service = DojoRuns(session)
        done = await service.get(run.id)
        first = await service.results(run.id, RunResultsQuery(limit=150))
        rest = await service.results(
            run.id, RunResultsQuery(after=first.next_after, limit=150)
        )
        listed = await service.list(RunListQuery(dataset_id=view.id))
    assert done.status == "succeeded", done.error
    assert (done.points_read, done.result_count) == (600, 200)
    assert done.started_at and done.finished_at
    assert [item.sequence for item in first.items + rest.items] == list(range(1, 201))
    assert rest.next_after is None
    assert first.items[0].phase == "warmup" and first.items[0].score is None
    assert rest.items[-1].phase == "operational"
    assert rest.items[-1].timestamp == T0 + timedelta(minutes=199)
    assert [item.id for item in listed.items] == [run.id]


@pytest.mark.asyncio
async def test_a_run_that_compares_calibration_methods_is_scored_per_method(sessions):
    """Queued through the service, replayed by the worker, read as metrics."""
    engine, factory = sessions
    creator, view = await dataset(factory)
    async with factory() as session:
        runs = DojoRuns(session)
        run = await runs.create(
            request(view, compare_calibration=True), created_by=creator
        )
        plain = await runs.create(request(view), created_by=creator)
        with pytest.raises(ValidationError, match="conformal martingale"):
            await runs.create(
                request(
                    view,
                    definition=quick("static_baseline"),
                    compare_calibration=True,
                ),
                created_by=creator,
            )
    assert run.compares_calibration and not plain.compares_calibration

    worker = DojoWorker(engine, WorkerOptions(worker_id="w", write_batch=40))
    assert await worker.run_once() and await worker.run_once()

    async with factory() as session:
        metrics = DojoMetrics(session)
        comparison = await metrics.calibration(run.id)
        own = await metrics.run(run.id)
        with pytest.raises(ConflictError, match="compared no calibration methods"):
            await metrics.calibration(plain.id)
    methods = comparison.methods
    assert [item.method for item in methods] == ["fixed_split", *CALIBRATORS]
    assert [item.own for item in methods] == [True] + [False] * 15
    assert (methods[0].name, methods[0].family) == ("Fixed split", "fixed")
    assert (methods[2].name, methods[2].family) == ("ACI", "conformal")
    assert all(item.failed is None for item in methods)
    # The design's quantile of 1.0 is the largest of the 40 calibration scores.
    assert comparison.alpha == pytest.approx(1 / 41)
    assert comparison.consecutive == 1
    assert 0 < comparison.results < 200
    assert comparison.scored_to == T0 + timedelta(minutes=199)
    # The run's own row counts the alarms the run raised.
    assert methods[0].alarm_count == own.alarm_count
    assert all(
        item.alarm_share == item.alarm_count / comparison.results for item in methods
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda body, view: body.bindings.pop("voltage"), "every input slot"),
        (
            lambda body, view: body.bindings.update(voltage="missing"),
            "no series 'missing'",
        ),
        (
            lambda body, view: body.bindings.update(voltage=view.series[1].id),
            "at most one input slot",
        ),
    ],
)
async def test_bindings_must_cover_each_slot_with_one_series(sessions, change, message):
    _, factory = sessions
    creator, view = await dataset(factory, minutes=3)
    body = request(view)
    change(body, view)
    async with factory() as session:
        with pytest.raises(ValidationError, match=message):
            await DojoRuns(session).create(body, created_by=creator)


@pytest.mark.asyncio
async def test_a_series_in_another_unit_is_refused(sessions):
    _, factory = sessions
    creator, view = await dataset(factory, minutes=3)
    async with factory() as session:
        series = await session.get(DojoSeries, view.series[0].id)
        series.unit = "V"
        await session.commit()
    body = request(view)
    data = body.definition.model_dump(mode="json")
    data["input_slots"][0]["unit"] = "kV"
    body = body.model_copy(
        update={"definition": type(body.definition).model_validate(data)}
    )
    async with factory() as session:
        with pytest.raises(ValidationError, match="is in V but input 'voltage'"):
            await DojoRuns(session).create(body, created_by=creator)


@pytest.mark.asyncio
async def test_cancel_and_delete_follow_the_run_status(sessions):
    engine, factory = sessions
    creator, view = await dataset(factory, minutes=3)
    async with factory() as session:
        service = DojoRuns(session)
        queued = await service.create(request(view), created_by=creator)
        with pytest.raises(ConflictError, match="Cancel the run"):
            await service.remove(queued.id)
    async with factory() as session:
        with pytest.raises(ConflictError, match="Cancel the dataset's runs"):
            await DojoDatasets(session).remove(view.id)
    async with factory() as session:
        cancelled = await DojoRuns(session).cancel(queued.id)
    assert cancelled.status == "cancelled" and cancelled.finished_at
    # The worker never picks up a cancelled run.
    assert not await DojoWorker(engine, WorkerOptions(worker_id="w")).run_once()
    async with factory() as session:
        service = DojoRuns(session)
        with pytest.raises(ConflictError, match="already cancelled"):
            await service.cancel(queued.id)
        await service.remove(queued.id)
        with pytest.raises(NotFoundError):
            await service.get(queued.id)


@pytest.mark.asyncio
async def test_deleting_a_dataset_removes_its_finished_runs_and_results(sessions):
    engine, factory = sessions
    creator, view = await dataset(factory, minutes=20)
    async with factory() as session:
        await DojoRuns(session).create(request(view), created_by=creator)
    await DojoWorker(engine, WorkerOptions(worker_id="w")).run_once()
    async with factory() as session:
        await DojoDatasets(session).remove(view.id)
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(DojoRun)) == 0
        assert (
            await session.scalar(select(func.count()).select_from(DojoRunResult)) == 0
        )


@pytest.mark.asyncio
async def test_more_waiting_runs_than_the_limit_are_refused(sessions, monkeypatch):
    monkeypatch.setattr(runs_module, "MAX_ACTIVE_RUNS", 1)
    _, factory = sessions
    creator, view = await dataset(factory, minutes=3)
    async with factory() as session:
        service = DojoRuns(session)
        await service.create(request(view), created_by=creator)
        with pytest.raises(ConflictError, match="At most 1 runs"):
            await service.create(request(view), created_by=creator)


@pytest.mark.asyncio
async def test_concurrent_requests_cannot_exceed_active_run_limit(
    sessions, monkeypatch
):
    monkeypatch.setattr(runs_module, "MAX_ACTIVE_RUNS", 1)
    _, factory = sessions
    creator, view = await dataset(factory, minutes=3)

    async def create():
        async with factory() as session:
            return await DojoRuns(session).create(request(view), created_by=creator)

    results = await asyncio.gather(
        *(create() for _ in range(8)), return_exceptions=True
    )
    assert sum(isinstance(result, ConflictError) for result in results) == 7
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(DojoRun)) == 1


def app(factory):
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")

    async def database():
        async with factory() as session:
            yield session

    application.dependency_overrides[get_db_async] = database
    return application


@pytest.mark.asyncio
async def test_routes_queue_and_cancel_runs(sessions):
    _, factory = sessions
    creator, view = await dataset(factory, minutes=3)
    async with factory() as session:
        admin = await session.get(User, creator)
    headers = {"Authorization": f"Bearer {access_token(admin)}"}
    async with asgi_client(app(factory)) as client:
        created = await client.post(
            "/api/v1/dojo/runs",
            json=request(view).model_dump(mode="json"),
            headers=headers,
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["id"]
        cancelled = await client.post(
            f"/api/v1/dojo/runs/{run_id}/cancel", headers=headers
        )
        results = await client.get(
            f"/api/v1/dojo/runs/{run_id}/results", headers=headers
        )
        deleted = await client.delete(f"/api/v1/dojo/runs/{run_id}", headers=headers)
        broken = await client.post(
            "/api/v1/dojo/runs",
            json={**request(view).model_dump(mode="json"), "bindings": {"x": "y"}},
            headers=headers,
        )
    assert created.json()["created_by"] == creator
    assert cancelled.json()["status"] == "cancelled"
    assert results.json() == {"items": [], "next_after": None}
    assert deleted.status_code == 204
    assert broken.status_code == 422
