"""A Dojo run's design becomes a library template, with its tested inputs."""

import pytest
import pytest_asyncio
from aberration_core.db.base import get_db_async
from aberration_core.db.models import (
    DeploymentMaintenance,
    DojoDataset,
    DojoPoint,
    DojoRun,
    DojoRunResult,
    DojoSeries,
    MemberRole,
    MonitoringPipeline,
    PipelineRevision,
    User,
)
from aberration_core.schemas.dojo import CsvImportQuery, RunCreate, RunPromote
from aberration_tactic_middleware.api.v1.dojo import router
from aberration_tactic_middleware.domain import ConflictError, NotFoundError
from aberration_tactic_middleware.services.dojo.datasets import DojoDatasets
from aberration_tactic_middleware.services.dojo.runs import DojoRuns
from aberration_tactic_middleware.services.pipelines.library import PipelineLibrary
from fastapi import FastAPI
from sqlalchemy import select

from tests.support.env import set_auth_env
from tests.support.http import asgi_client
from tests.support.membership import bootstrap
from tests.support.pipelines import quick
from tests.support.tokens import access_token

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
            DojoRun,
            DojoRunResult,
            MonitoringPipeline,
            PipelineRevision,
        ):
            await connection.run_sync(table.__table__.create)
    return engine, factory


async def queued_run(factory):
    creator = await bootstrap(factory)
    rows = "\n".join(f"2024-01-01T00:0{i}:00Z,{i},{i},{20 + i}" for i in range(3))
    async with factory() as session:
        view = await DojoDatasets(session).import_csv(
            f"time,u,i,t\n{rows}\n".encode(),
            CsvImportQuery(name="Old trips"),
            created_by=creator,
        )
        # As if the first two series were copied from recorded readings.
        for series, reading in zip(view.series, ("volts", "amps"), strict=False):
            (await session.get(DojoSeries, series.id)).reading_id = reading
        await session.commit()
        run = await DojoRuns(session).create(
            RunCreate(
                dataset_id=view.id,
                name="iForest",
                definition=quick(),
                bindings={
                    slot: series.id
                    for slot, series in zip(SLOTS, view.series, strict=True)
                },
            ),
            created_by=creator,
        )
    return creator, run


@pytest.mark.asyncio
async def test_a_run_becomes_a_template_with_its_slots_and_readings(sessions):
    _, factory = sessions
    _, run = await queued_run(factory)
    async with factory() as session:
        promoted = await DojoRuns(session).promote(
            run.id, RunPromote(name=" Charger iForest ", description="From the Dojo")
        )
    async with factory() as session:
        template = await PipelineLibrary(session).get(promoted.pipeline_id)
    assert promoted.pipeline_name == template.name == "Charger iForest"
    assert template.description == "From the Dojo"
    assert template.draft.model_dump(mode="json") == run.definition
    assert template.revisions == []
    assert [
        (item.slot_id, item.series_name, item.reading_id) for item in promoted.bindings
    ] == [
        ("voltage", "u", "volts"),
        ("current", "i", "amps"),
        ("temperature", "t", None),
    ]
    assert [item.slot_label for item in promoted.bindings] == [
        slot.label for slot in quick().input_slots
    ]


@pytest.mark.asyncio
async def test_promotion_needs_a_run_and_pipeline_authoring(sessions, monkeypatch):
    _, factory = sessions
    _, run = await queued_run(factory)
    async with factory() as session:
        with pytest.raises(NotFoundError):
            await DojoRuns(session).promote("missing", RunPromote(name="x"))
    monkeypatch.setattr(
        "aberration_tactic_middleware.services.pipelines.library.require_authoring",
        lambda: (_ for _ in ()).throw(ConflictError("Pipeline authoring is disabled")),
    )
    async with factory() as session:
        with pytest.raises(ConflictError, match="authoring is disabled"):
            await DojoRuns(session).promote(run.id, RunPromote(name="x"))


def app(factory):
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")

    async def database():
        async with factory() as session:
            yield session

    application.dependency_overrides[get_db_async] = database
    return application


@pytest.mark.asyncio
async def test_promotion_also_needs_manage_monitors(sessions):
    _, factory = sessions
    creator, run = await queued_run(factory)
    async with factory() as session:
        session.add(MemberRole(id="trainer", name="Trainer", permissions=["use_dojo"]))
        session.add(
            User(
                email="trainer@example.com",
                hashed_password="h",
                role="trainer",
                is_verified=True,
            )
        )
        await session.commit()
    async with factory() as session:
        admin = await session.get(User, creator)
        trainer = await session.scalar(
            select(User).where(User.email == "trainer@example.com")
        )
    body = {"name": "From the Dojo"}
    async with asgi_client(app(factory)) as client:
        refused = await client.post(
            f"/api/v1/dojo/runs/{run.id}/promote",
            json=body,
            headers={"Authorization": f"Bearer {access_token(trainer)}"},
        )
        read = await client.get(
            f"/api/v1/dojo/runs/{run.id}",
            headers={"Authorization": f"Bearer {access_token(trainer)}"},
        )
        created = await client.post(
            f"/api/v1/dojo/runs/{run.id}/promote",
            json=body,
            headers={"Authorization": f"Bearer {access_token(admin)}"},
        )
    assert refused.status_code == 403
    assert "manage_monitors" in refused.text
    assert read.status_code == 200
    assert created.status_code == 201, created.text
    assert created.json()["pipeline_name"] == "From the Dojo"
