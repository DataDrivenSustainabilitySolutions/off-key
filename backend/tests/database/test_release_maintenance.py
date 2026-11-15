"""Verify release locking, retries and migration transactions in isolated databases."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from off_key_core.db import collection_runtime
from off_key_core.db.collection import lock_collection_configuration
from off_key_core.db.maintenance import (
    DeploymentInProgressError,
    require_application_writes,
)
from off_key_core.db.migrate import (
    BASELINE,
    LEDGER,
    MIGRATION_LOCK,
    RetiredSchemaError,
    apply_migrations,
    migration_files,
    migration_status,
    verify_migrations,
)
from off_key_core.db.models import (
    DeploymentMaintenance,
    MonitoringEvidence,
    MonitoringService,
    PipelineRun,
)
from off_key_tactic_middleware import deployment
from off_key_tactic_middleware.services.accounts.members import MemberService
from off_key_tactic_middleware.services.catalogue.system_ingress import (
    SYSTEM_INGRESS_LOCK,
)
from off_key_tactic_middleware.services.orchestration.radar import (
    RadarOrchestrationService,
)
from off_key_tactic_middleware.services.pipelines import release
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from tests.support.env import DATABASE_ENVIRONMENT, set_environment
from tests.support.form_pipeline import form_launch, stored_revision


class _Preflight:
    """A release's replacement monitors pass preflight on the pinned image."""

    def __init__(self, workloads):
        pass

    async def resolve_image(self):
        return f"registry/radar@sha256:{'c' * 64}"

    async def run(self, *args):
        return {"succeeded": True}


def test_read_only_schema_verification_requires_a_complete_existing_ledger(
    disposable_database,
):
    with disposable_database.begin() as connection:
        before = inspect(connection).get_table_names()
        with pytest.raises(ValueError, match="ledger is missing"):
            verify_migrations(connection)
        assert inspect(connection).get_table_names() == before
        apply_migrations(connection)
        assert verify_migrations(connection)["pending"] == []
        later = migration_files() | {"001_later.sql": "SELECT 1;"}
        with pytest.raises(ValueError, match="fully applied"):
            verify_migrations(connection, later)


def test_fresh_database_records_the_baseline_and_later_migrations_run_once(
    disposable_database,
):
    with disposable_database.begin() as connection:
        assert migration_status(connection) == {
            "pending": [BASELINE],
            "applied": [],
            "fresh": True,
        }
        assert apply_migrations(connection) == {"applied": [BASELINE], "fresh": True}
        assert apply_migrations(connection)["applied"] == []
        later = migration_files() | {
            "001_later.sql": "CREATE TABLE release_probe (id integer);"
        }
        assert apply_migrations(connection, later)["applied"] == ["001_later.sql"]
        assert inspect(connection).has_table("release_probe")
        assert apply_migrations(connection, later)["applied"] == []
        changed = later | {"001_later.sql": "SELECT 1;"}
        with pytest.raises(ValueError, match="history differs"):
            migration_status(connection, changed)


@pytest.mark.parametrize(
    "history",
    ["retired_ledger", "empty_ledger", "no_ledger", "unknown_tables"],
)
def test_a_database_from_before_the_baseline_is_refused_unchanged(
    disposable_database, history
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        if history == "retired_ledger":
            connection.execute(text(f"DELETE FROM {LEDGER}"))
            connection.execute(
                text(
                    f"INSERT INTO {LEDGER} (version, checksum) "
                    "VALUES ('035_telemetry_log.sql', 'retired')"
                )
            )
        elif history == "empty_ledger":
            connection.execute(text(f"DELETE FROM {LEDGER}"))
        elif history == "no_ledger":
            connection.execute(text(f"DROP TABLE {LEDGER}"))
        else:
            for table in reversed(inspect(connection).get_table_names()):
                connection.execute(text(f"DROP TABLE {table} CASCADE"))
            connection.execute(text("CREATE TABLE unrelated (id integer)"))
    with disposable_database.begin() as connection:
        before = sorted(inspect(connection).get_table_names())
        with pytest.raises(RetiredSchemaError, match="reset it"):
            migration_status(connection)
        with pytest.raises(RetiredSchemaError):
            apply_migrations(connection)
    with disposable_database.begin() as connection:
        assert sorted(inspect(connection).get_table_names()) == before


def test_failed_migration_rolls_back_ddl_and_ledger_and_lock_blocks_competitors(
    disposable_database,
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
    migrations = migration_files() | {
        "001_failure.sql": "CREATE TABLE release_probe (id integer); SELECT 1 / 0;"
    }
    with (
        pytest.raises(Exception, match="division by zero"),
        disposable_database.begin() as connection,
    ):
        apply_migrations(connection, migrations)
    with (
        disposable_database.begin() as owner,
        disposable_database.begin() as competitor,
    ):
        assert not inspect(owner).has_table("release_probe")
        assert migration_status(owner)["pending"] == []
        owner.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK}
        )
        with pytest.raises(ValueError, match="Another database upgrade"):
            apply_migrations(competitor)


@pytest.mark.asyncio
async def test_ingress_ownership_does_not_block_account_management_or_migrations(
    disposable_database,
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    try:
        with disposable_database.connect() as ownership:
            ownership.execute(
                text("SELECT pg_advisory_lock(:key)"), {"key": SYSTEM_INGRESS_LOCK}
            )
            ownership.commit()
            try:
                with disposable_database.begin() as connection:
                    assert apply_migrations(connection)["applied"] == []
                async with AsyncSession(engine) as session:
                    await session.execute(text("SET LOCAL lock_timeout = '1s'"))
                    await MemberService(session)._lock_membership()
            finally:
                ownership.execute(
                    text("SELECT pg_advisory_unlock(:key)"),
                    {"key": SYSTEM_INGRESS_LOCK},
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_monitor_cutover_blocks_writes_preserves_intent_and_resumes_once(
    disposable_database, monkeypatch
):
    set_environment(monkeypatch, DATABASE_ENVIRONMENT)
    monkeypatch.setattr(release, "PipelinePreflight", _Preflight)
    with disposable_database.begin() as connection:
        apply_migrations(connection)
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    revision = "a" * 40
    config = form_launch(
        container_name="first",
        mqtt_topics=["telemetry/charger-1/sine"],
        model_type="pyod_iforest",
    )
    config2 = config.model_copy(update={"container_name": "stopping"})
    stopped = []

    async def request_stop(identifier):
        stopped.append(identifier)

    workloads = SimpleNamespace(request_stop=request_stop, wait_stopped=AsyncMock())
    removed = []
    created = []

    async def remove(identifier):
        removed.append(identifier)
        return True

    async def create(identifier, environment):
        created.append(identifier)
        return SimpleNamespace(id="new-" + identifier)

    workloads.remove = remove
    workloads.create = create
    workloads.ensure = create
    workloads.validate_started = AsyncMock()
    workloads.get_status_and_labels = AsyncMock(return_value=("running", {}))
    snapshot = SimpleNamespace(
        revision=1,
        collection={"revision": 1, "status": "applied"},
        catalog=SimpleNamespace(
            streams=lambda **kw: [
                SimpleNamespace(
                    accepted_topic=config.mqtt_topics[0],
                    value_type="number",
                    signature=("fixture",),
                )
            ],
        ),
    )
    monkeypatch.setattr(
        collection_runtime, "read_collection_runtime", AsyncMock(return_value=snapshot)
    )
    monkeypatch.setattr(
        "off_key_tactic_middleware.services.orchestration.radar_environment."
        "validate_model_params",
        lambda *args, **kwargs: {},
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add_all(stored_revision(config))
            await session.flush()
            session.add_all(
                [
                    MonitoringService(
                        id="old-id",
                        container_id="old",
                        container_name="first",
                        status=True,
                        mqtt_topic=config.mqtt_topics,
                        launch_config=config.model_dump(mode="json"),
                    ),
                    MonitoringService(
                        id="stopping-id",
                        container_id="stopping",
                        container_name="stopping",
                        status=True,
                        mqtt_topic=config.mqtt_topics,
                        launch_config=config2.model_dump(mode="json"),
                        stop_requested_at=datetime.now(UTC),
                    ),
                ]
            )
            session.add(
                MonitoringEvidence(
                    service_id="old-id",
                    timestamp=datetime.now(UTC),
                    sequence_number=1,
                    charger_id="charger-1",
                    sensor_set=["sine"],
                    input_timestamps={},
                    strategy="static_baseline",
                    p_value=0.1,
                    threshold=0.5,
                )
            )
            await session.commit()
            orchestration = RadarOrchestrationService(session)
            orchestration.workloads = workloads
            await deployment.begin(session, orchestration, revision)
            assert sorted(removed) == ["old", "stopping"]
            # The pool ended both children before their rows were removed.
            assert sorted(stopped) == ["old", "stopping"]
            operation = await session.get(DeploymentMaintenance, 1)
            assert operation.phase == "stopped"
            async with AsyncSession(engine) as competitor:
                await lock_collection_configuration(competitor)
                with pytest.raises(DeploymentInProgressError):
                    await require_application_writes(competitor)
                await competitor.rollback()
            with pytest.raises(ValueError, match="different release"):
                await deployment.prepare_operation(session, workloads, "b" * 40)
            await session.rollback()
            await deployment.resume(session, orchestration, revision)
            await deployment.resume(session, orchestration, revision)
            assert len(created) == 1
            operation = await session.get(DeploymentMaintenance, 1)
            replacement = operation.monitors[0]["replacement_id"]
            assert replacement != "old-id"
            assert await session.get(MonitoringService, "old-id") is None
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM monitoring_evidence "
                        "WHERE service_id='old-id'"
                    )
                )
                == 1
            )
            assert operation.monitors[1]["replacement_id"] is None
            with pytest.raises(ValueError, match="healthy runtime"):
                await deployment.finish(session, revision)
            await session.rollback()
            worker = await session.get(MonitoringService, replacement)
            worker.operational_updated_at = datetime.now(UTC)
            worker.operational_stage = "waiting_for_data"
            await session.commit()
            await deployment.finish(session, revision)
            await lock_collection_configuration(session)
            await require_application_writes(session)
            await session.rollback()
            # Static releases use the same durable reservation, without stopping
            # or replacing the already healthy monitor that survived cutover.
            static_revision = "b" * 40
            await deployment.reserve(session, static_revision)
            async with AsyncSession(engine) as competitor:
                await lock_collection_configuration(competitor)
                with pytest.raises(DeploymentInProgressError):
                    await require_application_writes(competitor)
                await competitor.rollback()
            with pytest.raises(ValueError, match="different release"):
                await deployment.reserve(session, "c" * 40)
            await session.rollback()
            await deployment.finish_static(session, static_revision)
            assert len(created) == 1
            assert await session.get(MonitoringService, replacement) is not None
            await lock_collection_configuration(session)
            await require_application_writes(session)
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_fresh_release_reservation_precedes_schema_bootstrap(disposable_database):
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    try:
        async with AsyncSession(engine) as session:
            assert (await deployment.reserve(session, "a" * 40))[
                "phase"
            ] == "uninitialized"
            assert await session.scalar(text("SELECT to_regclass('services')")) is None
            assert (
                await session.scalar(
                    text("SELECT to_regclass('deployment_maintenance')")
                )
                is None
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_release_retains_pending_monitor_claim_until_confirmed_removal(
    disposable_database, monkeypatch
):
    monkeypatch.setattr(release, "PipelinePreflight", _Preflight)
    with disposable_database.begin() as connection:
        apply_migrations(connection)
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    config = form_launch(
        container_name="pending",
        mqtt_topics=["telemetry/charger-1/sine"],
    )
    workloads = SimpleNamespace(
        remove_intent=AsyncMock(
            side_effect=[RuntimeError("RADAR workload has not stopped"), False]
        ),
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add_all(stored_revision(config))
            await session.flush()
            session.add(
                MonitoringService(
                    id="pending-id",
                    container_id=None,
                    container_name=config.container_name,
                    status=True,
                    desired_state="running",
                    config_fingerprint="known-configuration",
                    lifecycle_version=1,
                    mqtt_topic=config.mqtt_topics,
                    launch_config=config.model_dump(mode="json"),
                )
            )
            await session.commit()
            orchestration = RadarOrchestrationService(session, workloads=workloads)
            with pytest.raises(ValueError, match="could not stop"):
                await deployment.begin(session, orchestration, "a" * 40)
            await session.rollback()
            retained = await session.get(MonitoringService, "pending-id")
            assert retained.desired_state == "deleted"
            assert retained.status
            assert retained.lifecycle_version == 2
            operation = await session.get(DeploymentMaintenance, 1)
            assert operation.phase == "preparing"
            assert operation.monitors[0]["stopped"] is False
            assert (await deployment.begin(session, orchestration, "a" * 40))[
                "phase"
            ] == "stopped"
            assert await session.get(MonitoringService, "pending-id") is None
            history = await session.scalar(
                select(PipelineRun).where(PipelineRun.service_id == "pending-id")
            )
            assert history.status == "stopped"
            assert history.ended_at is not None
            assert workloads.remove_intent.await_count == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_abort_reopens_writes_and_reports_monitors_left_stopped(
    disposable_database,
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    revision = "b" * 40
    try:
        async with AsyncSession(engine) as session:
            session.add(
                PipelineRun(
                    id="replacement-run",
                    service_id="replacement",
                    launch_config={},
                    status="starting",
                )
            )
            session.add(
                DeploymentMaintenance(
                    id=1,
                    revision=revision,
                    phase="restarted",
                    monitors=[
                        {"previous_id": "kept", "replacement_id": "replacement"},
                        {
                            "previous_id": "retired",
                            "replacement_id": None,
                            "config": None,
                            "stopped": True,
                        },
                    ],
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()
            with pytest.raises(DeploymentInProgressError):
                await require_application_writes(session)
            await session.rollback()
            with pytest.raises(ValueError, match="No matching"):
                await deployment.abort(session, "c" * 40)
            await session.rollback()

            result = await deployment.abort(session, revision)

            assert result == {
                "phase": "complete",
                "aborted": True,
                "aborted_phase": "restarted",
                "restarted": ["replacement"],
                "not_restarted": ["retired"],
            }
            await require_application_writes(session)
            run = await session.get(PipelineRun, "replacement-run")
            assert run.status == "running"
            assert (await deployment.abort(session, revision))["aborted"] is False
    finally:
        await engine.dispose()
