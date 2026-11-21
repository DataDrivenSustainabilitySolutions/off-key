"""An agent's key deletes the Dojo datasets and runs it made, and nothing else.

Five agents may test designs on a production installation at once. Each
leaves datasets and runs behind and may clean them up, but a member's work,
another key's work and the test a proposal or a monitor names as its evidence
stay.
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from off_key_core.auth.agents import agent_key_digest, new_agent_key
from off_key_core.db.models import (
    Agent,
    DojoDataset,
    DojoRun,
    MonitorEventRecord,
    PipelineProposal,
    User,
)
from off_key_core.schemas.dojo import (
    CsvImportQuery,
    DatasetListQuery,
    RunCreate,
    RunListQuery,
)
from off_key_mqtt_radar.dojo.worker import DojoWorker, WorkerOptions
from off_key_tactic_middleware.domain import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from off_key_tactic_middleware.services.dojo.datasets import DojoDatasets
from off_key_tactic_middleware.services.dojo.runs import DojoRuns
from sqlalchemy import func, select

from tests.support.dojo import create_dojo_tables
from tests.support.env import set_auth_env
from tests.support.membership import bootstrap
from tests.support.pipelines import quick

T0 = datetime(2024, 1, 1, tzinfo=UTC)
SLOTS = ("voltage", "current", "temperature")


@pytest_asyncio.fixture
async def sessions(member_database, monkeypatch):
    set_auth_env(monkeypatch)
    engine, factory = member_database
    async with engine.begin() as connection:
        await connection.run_sync(create_dojo_tables)
    return engine, factory


async def agent_named(factory, name: str) -> Agent:
    async with factory() as session:
        agent = Agent(
            name=name, key_hash=agent_key_digest(new_agent_key()), key_hint="abcd"
        )
        session.add(agent)
        await session.commit()
        return agent


async def made(factory, *, member: int | None = None, agent: Agent | None = None):
    """A small dataset, made by a member or by an agent's key."""
    rows = "\n".join(
        f"{(T0 + timedelta(minutes=i)).isoformat()},{i % 7},{i % 5},{20 + i % 3}"
        for i in range(20)
    )
    async with factory() as session:
        return await DojoDatasets(session).import_csv(
            f"time,u,i,t\n{rows}\n".encode(),
            CsvImportQuery(name="Old trips"),
            created_by=member,
            created_by_agent=agent,
        )


async def queued(factory, view, *, member=None, agent=None) -> str:
    request = RunCreate(
        dataset_id=view.id,
        definition=quick(),
        bindings={
            slot: series.id for slot, series in zip(SLOTS, view.series, strict=True)
        },
    )
    async with factory() as session:
        run = await DojoRuns(session).create(
            request, created_by=member, created_by_agent=agent
        )
    return run.id


async def replayed(engine) -> None:
    worker = DojoWorker(engine, WorkerOptions(worker_id="w"))
    while await worker.run_once():
        pass


async def count(factory, table) -> int:
    async with factory() as session:
        return await session.scalar(select(func.count()).select_from(table))


@pytest.mark.asyncio
async def test_a_key_lists_and_deletes_only_what_it_made(sessions):
    engine, factory = sessions
    member = await bootstrap(factory)
    mine, other = await agent_named(factory, "Night"), await agent_named(factory, "Day")
    own = await made(factory, agent=mine)
    theirs = await made(factory, agent=other)
    members = await made(factory, member=member)
    assert (own.created_by, own.created_by_agent) == (None, "Night")
    own_run = await queued(factory, own, agent=mine)
    their_run = await queued(factory, theirs, agent=other)
    member_run = await queued(factory, members, member=member)
    await replayed(engine)

    async with factory() as session:
        datasets = DojoDatasets(session)
        runs = DojoRuns(session)
        listed = await datasets.list(DatasetListQuery(mine=True), mine)
        assert [item.id for item in listed.items] == [own.id]
        assert len((await datasets.list(DatasetListQuery(), mine)).items) == 3
        assert [
            item.id for item in (await runs.list(RunListQuery(mine=True), mine)).items
        ] == [own_run]
        # A member's own are theirs alone too.
        member_row = await session.get(User, member)
        assert member_row is not None
        assert [
            item.id
            for item in (await runs.list(RunListQuery(mine=True), member_row)).items
        ] == [member_run]

    for run_id in (their_run, member_run):
        async with factory() as session:
            with pytest.raises(ForbiddenError, match="only the runs it queued"):
                await DojoRuns(session).remove(run_id, mine)
    for view in (theirs, members):
        async with factory() as session:
            with pytest.raises(ForbiddenError, match="only the datasets it made"):
                await DojoDatasets(session).remove(view.id, mine)

    async with factory() as session:
        await DojoRuns(session).remove(own_run, mine)
    async with factory() as session:
        await DojoDatasets(session).remove(own.id, mine)
        with pytest.raises(NotFoundError):
            await DojoDatasets(session).get(own.id)
    assert await count(factory, DojoDataset) == 2
    assert await count(factory, DojoRun) == 2


@pytest.mark.asyncio
async def test_a_key_cancels_only_its_own_runs(sessions):
    _, factory = sessions
    member = await bootstrap(factory)
    mine = await agent_named(factory, "Night")
    view = await made(factory, agent=mine)
    own_run = await queued(factory, view, agent=mine)
    member_run = await queued(factory, view, member=member)
    async with factory() as session:
        with pytest.raises(ForbiddenError, match="cancels and deletes only"):
            await DojoRuns(session).cancel(member_run, mine)
    async with factory() as session:
        assert (await DojoRuns(session).cancel(own_run, mine)).status == "cancelled"


@pytest.mark.asyncio
async def test_a_key_cannot_take_others_runs_with_its_dataset(sessions):
    """Deleting a dataset deletes the runs on it, so every one must be the key's."""
    engine, factory = sessions
    member = await bootstrap(factory)
    mine = await agent_named(factory, "Night")
    view = await made(factory, agent=mine)
    await queued(factory, view, agent=mine)
    await queued(factory, view, member=member)
    await replayed(engine)
    async with factory() as session:
        with pytest.raises(ForbiddenError, match="runs that a member or another key"):
            await DojoDatasets(session).remove(view.id, mine)
    # The member may, as before.
    async with factory() as session:
        await DojoDatasets(session).remove(view.id)
    assert await count(factory, DojoRun) == 0


def proposed(run_id: str, agent: Agent, status: str) -> PipelineProposal:
    return PipelineProposal(
        id=f"proposal-{status}",
        name="Pump",
        reason="Why",
        definition={},
        layout={},
        bindings={},
        test_run_id=run_id,
        author=agent.name,
        author_kind="agent",
        agent_id=agent.id,
        status=status,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_the_test_a_proposal_or_monitor_names_stays_as_evidence(sessions):
    engine, factory = sessions
    mine = await agent_named(factory, "Night")
    view = await made(factory, agent=mine)
    waiting = await queued(factory, view, agent=mine)
    accepted = await queued(factory, view, agent=mine)
    started = await queued(factory, view, agent=mine)
    declined = await queued(factory, view, agent=mine)
    await replayed(engine)
    async with factory() as session:
        session.add_all(
            [
                proposed(waiting, mine, "open"),
                proposed(accepted, mine, "accepted"),
                proposed(declined, mine, "declined"),
                MonitorEventRecord(
                    service_id="service-1",
                    event="started",
                    author=mine.name,
                    author_kind="agent",
                    agent_id=mine.id,
                    test_run_id=started,
                ),
            ]
        )
        await session.commit()

    for run_id in (waiting, accepted, started):
        async with factory() as session:
            with pytest.raises(ConflictError, match="names this test as its evidence"):
                await DojoRuns(session).remove(run_id, mine)
    async with factory() as session:
        with pytest.raises(ConflictError, match="evidence"):
            await DojoDatasets(session).remove(view.id, mine)

    # A declined proposal asks nothing of its test any more.
    async with factory() as session:
        await DojoRuns(session).remove(declined, mine)
    # Once withdrawn, a waiting proposal's test may go too.
    async with factory() as session:
        row = await session.get(PipelineProposal, "proposal-open")
        assert row is not None
        row.status = "withdrawn"
        await session.commit()
    async with factory() as session:
        await DojoRuns(session).remove(waiting, mine)
    assert await count(factory, DojoRun) == 2
