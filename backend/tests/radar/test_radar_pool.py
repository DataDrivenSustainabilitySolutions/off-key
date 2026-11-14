"""The RADAR pool leases workloads from the database and runs each as a child.

Each test runs a real pool worker against a disposable database; only what a
child executes is a stand-in.
"""

import asyncio
import json

import pytest
import pytest_asyncio
from off_key_core.db.migrate import apply_migrations
from off_key_core.db.workloads import RadarWorkload
from off_key_mqtt_radar.pool.settings import RadarPoolSettings
from off_key_tactic_middleware.services.orchestration.radar_workloads import (
    RadarWorkloadManager,
)
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.support.radar_pool import RUNTIME, eventually, running_pool


@pytest_asyncio.fixture
async def pool_database(disposable_database):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    try:
        yield engine, async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def quick_controller(monkeypatch):
    monkeypatch.setenv("TACTIC_RADAR_STARTUP_GRACE_SECONDS", "0")
    monkeypatch.setenv("TACTIC_RADAR_STOP_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("TACTIC_POOL_MEMORY_LIMIT", "512m")


async def submit(manager, name="radar-one", *, kind="monitor", restart=True, **spec):
    return await manager.submit(
        name=name,
        kind=kind,
        module=spec.pop("module", "off_key_mqtt_radar"),
        runtime=spec.pop("runtime", RUNTIME),
        environment=spec.pop("environment", {"SERVICE_ID": name}),
        labels=spec.pop("labels", {"radar_service_id": name}),
        restart=restart,
    )


async def row(sessions, workload_id) -> RadarWorkload | None:
    async with sessions() as session:
        return await session.get(RadarWorkload, workload_id)


async def state_of(sessions, workload_id, expected):
    async def check():
        current = await row(sessions, workload_id)
        return current if current is not None and current.state == expected else None

    return await eventually(check)


@pytest.mark.asyncio
async def test_a_monitor_runs_until_asked_to_stop_and_then_is_removed(pool_database):
    engine, sessions = pool_database
    manager = RadarWorkloadManager(sessions)
    async with running_pool(engine):
        workload = await submit(manager)
        running = await state_of(sessions, workload.id, "running")
        assert running.worker_id == "pool-test"
        assert running.attempts == 1
        assert (await manager.get(workload.id)).state == "running"

        assert await manager.remove(workload.id) is True

        assert await row(sessions, workload.id) is None


@pytest.mark.asyncio
async def test_a_retried_submit_finds_the_row_an_earlier_attempt_made(pool_database):
    _, sessions = pool_database
    manager = RadarWorkloadManager(sessions)
    first = await submit(manager)
    second = await submit(manager, environment={"SERVICE_ID": "other"})
    assert second.id == first.id
    assert second.environment == {"SERVICE_ID": "radar-one"}


@pytest.mark.asyncio
async def test_only_a_replica_of_the_pinned_runtime_claims_a_workload(pool_database):
    engine, sessions = pool_database
    manager = RadarWorkloadManager(sessions)
    other = await submit(manager, "radar-other", runtime="registry/radar:next")
    async with running_pool(engine):
        mine = await submit(manager)
        await state_of(sessions, mine.id, "running")
        await asyncio.sleep(0.3)
        assert (await row(sessions, other.id)).state == "pending"


@pytest.mark.asyncio
async def test_a_replica_runs_no_more_children_than_its_capacity(pool_database):
    engine, sessions = pool_database
    manager = RadarWorkloadManager(sessions)
    first = await submit(manager, "radar-a")
    second = await submit(manager, "radar-b")
    async with running_pool(engine, capacity=1):
        await state_of(sessions, first.id, "running")
        await asyncio.sleep(0.3)
        assert (await row(sessions, second.id)).state == "pending"
        await manager.remove(first.id)
        await state_of(sessions, second.id, "running")


@pytest.mark.asyncio
async def test_a_crashed_monitor_restarts_until_its_crash_budget_is_spent(
    pool_database,
):
    engine, sessions = pool_database
    manager = RadarWorkloadManager(sessions)
    async with running_pool(engine, code="raise SystemExit(3)", max_restarts=3):
        workload = await submit(manager)
        failed = await state_of(sessions, workload.id, "failed")

    assert failed.attempts == 3
    assert failed.detail == "Crashed 3 times; not restarted"
    crashes = await manager.crashes(workload.id)
    assert [crash["task_id"] for crash in crashes] == [
        f"{workload.id}:3",
        f"{workload.id}:2",
        f"{workload.id}:1",
    ]
    assert {crash["exit_code"] for crash in crashes} == {3}
    assert crashes[0]["error"] == "exit code 3"


@pytest.mark.asyncio
async def test_a_child_past_its_memory_limit_is_killed_and_says_why(
    pool_database, monkeypatch
):
    monkeypatch.setenv("TACTIC_POOL_MEMORY_LIMIT", "192m")
    monkeypatch.setenv("TACTIC_RADAR_DEFAULT_MEMORY_LIMIT_MB", "128")
    monkeypatch.setenv("TACTIC_RADAR_DEFAULT_MAX_QUEUE_SIZE", "16")
    engine, sessions = pool_database
    manager = RadarWorkloadManager(sessions)
    grow = "import time; data = b'x' * (320 * 1024 * 1024); time.sleep(60)"
    async with running_pool(engine, code=grow, max_restarts=1):
        workload = await submit(manager)
        failed = await state_of(sessions, workload.id, "failed")

    (crash,) = failed.crashes
    assert crash["exit_code"] == 137
    assert "memory limit" in crash["hint"]


@pytest.mark.asyncio
async def test_a_one_off_job_reports_its_output_and_is_never_restarted(
    pool_database,
):
    engine, sessions = pool_database
    manager = RadarWorkloadManager(sessions)
    code = {
        "job.ok": "print('progress'); print('{\"ok\": true}')",
        "job.bad": "print('{\"ok\": false}'); raise SystemExit(1)",
    }
    async with running_pool(engine, code=code):
        ok = await submit(
            manager, "job-ok", kind="preflight", module="job.ok", restart=False
        )
        bad = await submit(
            manager, "job-bad", kind="preflight", module="job.bad", restart=False
        )
        finished = await state_of(sessions, ok.id, "complete")
        failed = await state_of(sessions, bad.id, "failed")

    assert json.loads(finished.output.splitlines()[-1]) == {"ok": True}
    assert failed.exit_code == 1
    assert failed.attempts == 1
    assert failed.crashes == []


@pytest.mark.asyncio
async def test_a_preflight_job_never_sees_the_pools_credentials(
    pool_database, monkeypatch
):
    """Monitors inherit the replica's login; a preflight job gets only its row."""
    engine, sessions = pool_database
    manager = RadarWorkloadManager(sessions)
    monkeypatch.setenv("POSTGRES_PASSWORD", "pool-secret")
    code = (
        "import json, os; print(json.dumps({k: os.environ.get(k) for k in "
        "('POSTGRES_PASSWORD', 'RADAR_PIPELINE_CONFIG')}))"
    )
    async with running_pool(engine, code=code):
        job = await submit(
            manager,
            "job",
            kind="preflight",
            restart=False,
            environment={"RADAR_PIPELINE_CONFIG": "{}"},
        )
        finished = await state_of(sessions, job.id, "complete")

    assert json.loads(finished.output.splitlines()[-1]) == {
        "POSTGRES_PASSWORD": None,
        "RADAR_PIPELINE_CONFIG": "{}",
    }


@pytest.mark.asyncio
async def test_a_stopped_replica_hands_its_workloads_to_another(pool_database):
    engine, sessions = pool_database
    manager = RadarWorkloadManager(sessions)
    async with running_pool(engine, worker_id="first"):
        workload = await submit(manager)
        await state_of(sessions, workload.id, "running")
    released = await row(sessions, workload.id)
    assert released.state == "pending"
    assert released.worker_id is None

    async with running_pool(engine, worker_id="second"):
        taken = await state_of(sessions, workload.id, "running")
        assert taken.worker_id == "second"


@pytest.mark.asyncio
async def test_an_expired_lease_is_taken_over_and_reads_as_pending_meanwhile(
    pool_database,
):
    engine, sessions = pool_database
    manager = RadarWorkloadManager(sessions)
    workload = await submit(manager)
    # A replica that died without releasing its row.
    async with sessions.begin() as session:
        await session.execute(
            update(RadarWorkload)
            .where(RadarWorkload.id == workload.id)
            .values(state="running", worker_id="dead", lease_expires_at=None)
        )
    assert (await manager.get(workload.id)).state == "pending"
    # A stop does not wait for a child that no lease protects.
    await manager.wait_stopped(workload.id)

    async with running_pool(engine):

        async def taken():
            current = await row(sessions, workload.id)
            return current.worker_id == "pool-test" and current

        current = await eventually(taken)
        assert current.state == "running"
        assert current.attempts == 1


@pytest.mark.asyncio
async def test_a_replica_that_cannot_renew_stops_its_children_before_the_lease_ends(
    pool_database,
):
    engine, sessions = pool_database
    manager = RadarWorkloadManager(sessions)
    async with running_pool(engine, lease_seconds=1.0) as pool:
        workload = await submit(manager)
        await state_of(sessions, workload.id, "running")
        child = pool.children[workload.id].process

        async def unreachable(*_args, **_kwargs):
            raise OSError("database unreachable")

        pool.renew = unreachable
        await eventually(lambda: _returned(child), within=5)
        current = await row(sessions, workload.id)
        # Fenced before its lease ended, so no two children ever overlap.
        assert child.returncode is not None
        assert current.state == "running"
        assert current.worker_id == "pool-test"
        assert pool.children == {}


@pytest.mark.asyncio
async def test_a_replica_whose_renewal_hangs_still_stops_its_children_in_time(
    pool_database,
):
    engine, sessions = pool_database
    manager = RadarWorkloadManager(sessions)
    async with running_pool(engine, lease_seconds=1.0) as pool:
        workload = await submit(manager)
        await state_of(sessions, workload.id, "running")
        child = pool.children[workload.id].process
        hung = asyncio.Event()

        async def hangs(*_args, **_kwargs):
            await hung.wait()

        pool.renew = hangs
        try:
            # The poll is stuck in renew; only the watchdog can fence.
            await eventually(lambda: _returned(child), within=5)
            assert pool.children == {}
            assert pool.healthy is False
        finally:
            hung.set()


@pytest.mark.asyncio
async def test_a_preflight_only_replica_leaves_monitors_to_the_pool(pool_database):
    engine, sessions = pool_database
    manager = RadarWorkloadManager(sessions)
    async with running_pool(engine, kinds=("preflight",)) as pool:
        monitor = await submit(manager)
        job = await submit(manager, "preflight-one", kind="preflight", restart=False)
        await state_of(sessions, job.id, "running")
        await asyncio.sleep(0.3)
        assert list(pool.children) == [job.id]
        assert (await row(sessions, monitor.id)).state == "pending"


async def _returned(process):
    return process.returncode is not None


@pytest.mark.asyncio
async def test_a_removed_row_ends_its_child(pool_database):
    engine, sessions = pool_database
    manager = RadarWorkloadManager(sessions)
    async with running_pool(engine) as pool:
        workload = await submit(manager)
        await state_of(sessions, workload.id, "running")
        child = pool.children[workload.id].process
        async with sessions.begin() as session:
            await session.delete(await session.get(RadarWorkload, workload.id))
        await eventually(lambda: _returned(child), within=5)


@pytest.mark.asyncio
async def test_listing_reads_every_monitor_in_one_query(pool_database):
    _, sessions = pool_database
    manager = RadarWorkloadManager(sessions)
    first = await submit(manager, "radar-a")
    await submit(manager, "job", kind="preflight", restart=False)
    assert await manager.list_managed_ids() == {first.id}
    assert await manager.statuses_and_labels([first.id, None, "missing"]) == [
        ("pending", {"radar_service_id": "radar-a"}),
        ("no_container_id", {}),
        ("not_found", {}),
    ]
    async with sessions() as session:
        assert len((await session.scalars(select(RadarWorkload))).all()) == 2


def test_a_lease_must_outlast_several_polls(monkeypatch):
    monkeypatch.setenv("RADAR_POOL_RUNTIME", RUNTIME)
    monkeypatch.setenv("RADAR_POOL_POLL_SECONDS", "5")
    monkeypatch.setenv("RADAR_POOL_LEASE_SECONDS", "10")
    with pytest.raises(ValidationError, match="four polls"):
        RadarPoolSettings()
    monkeypatch.setenv("RADAR_POOL_LEASE_SECONDS", "20")
    assert RadarPoolSettings().options().runtime == RUNTIME
