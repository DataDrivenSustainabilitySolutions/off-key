"""Verify release locking, retries and migration transactions in isolated databases."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import docker
import pytest
from aberration_core.db import collection_runtime
from aberration_core.db.collection import lock_collection_configuration
from aberration_core.db.maintenance import (
    DeploymentInProgressError,
    require_application_writes,
)
from aberration_core.db.migrate import (
    MIGRATION_LOCK,
    apply_migrations,
    migration_files,
    migration_status,
)
from aberration_core.db.models import (
    Charger,
    CollectionConfiguration,
    DeploymentMaintenance,
    MonitoringEvidence,
    MonitoringService,
    PipelineRun,
    Telemetry,
    User,
)
from aberration_core.schemas.system_collection import stable_key
from aberration_tactic_middleware import deployment
from aberration_tactic_middleware.services.accounts.members import MemberService
from aberration_tactic_middleware.services.catalogue.system_ingress import (
    SYSTEM_INGRESS_LOCK,
)
from aberration_tactic_middleware.services.orchestration import radar
from aberration_tactic_middleware.services.orchestration.radar import (
    RadarOrchestrationService,
)
from aberration_tactic_middleware.services.pipelines import release
from sqlalchemy import insert, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from tests.support.env import DATABASE_ENVIRONMENT, set_environment
from tests.support.form_pipeline import form_launch, stored_revision
from tests.support.schema_baselines import (
    EXPECTED_MIGRATIONS,
    migrations_from,
    remove_pipeline_schema,
    restore_entity_favorites,
    restore_retired_schema,
    restore_role_enum,
    rewind_ledger,
)


class _Preflight:
    """A release's replacement monitors pass preflight on the pinned image."""

    def __init__(self, workloads):
        pass

    async def resolve_image(self):
        return f"registry/radar@sha256:{'c' * 64}"

    async def run(self, *args):
        return {"succeeded": True}


def test_migration_history_is_the_expected_sequence():
    assert tuple(migration_files()) == EXPECTED_MIGRATIONS


def test_template_migration_preserves_existing_designs(disposable_database):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.execute(
            text("ALTER TABLE monitoring_pipelines DROP COLUMN is_template")
        )
        connection.execute(
            text(
                "DELETE FROM aberration_schema_migrations "
                "WHERE version >= '013_pipeline_templates.sql'"
            )
        )
        connection.execute(
            text(
                "INSERT INTO monitoring_pipelines "
                "(id,name,description,archived,version,draft,layout) "
                "VALUES ('existing','Existing template','',false,1,'{}','{}')"
            )
        )
        assert apply_migrations(connection)["applied"] == migrations_from(
            "013_pipeline_templates.sql"
        )
        assert (
            connection.scalar(
                text("SELECT is_template FROM monitoring_pipelines WHERE id='existing'")
            )
            is True
        )


def test_retired_schema_migration_keeps_the_telemetry_primary_key(
    disposable_database,
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        restore_retired_schema(connection)
        rewind_ledger(connection, "014_drop_unread_schema.sql")
    with disposable_database.begin() as connection:
        assert apply_migrations(connection)["applied"] == migrations_from(
            "014_drop_unread_schema.sql"
        )
        schema = inspect(connection)
        assert schema.get_pk_constraint("telemetry")["constrained_columns"] == [
            "charger_id",
            "timestamp",
            "type",
        ]
        assert "model_registry" not in schema.get_table_names()
        assert "stateful_set_name" not in {
            column["name"] for column in schema.get_columns("services")
        }


def save_catalogue(connection, *device_ids: str, bindings=None) -> None:
    """A saved catalogue with these devices and collection bindings, as
    migrations read them."""
    connection.execute(
        text(
            "INSERT INTO system_configuration (id, revision, document, updated_by) "
            "VALUES (1, 1, CAST(:document AS jsonb), 'test') "
            "ON CONFLICT (id) DO UPDATE SET document = EXCLUDED.document"
        ),
        {"document": json.dumps({"devices": [{"id": id} for id in device_ids]})},
    )
    connection.execute(
        text(
            "INSERT INTO system_collection_configuration (id, revision, document, "
            "ingress_status, collection_status, updated_by) "
            "VALUES (1, 1, CAST(:document AS jsonb), '{}', '{}', 'test') "
            "ON CONFLICT (id) DO UPDATE SET document = EXCLUDED.document"
        ),
        {"document": json.dumps({"bindings": bindings or {}})},
    )


def test_member_favorites_migration_keeps_entity_favorites(disposable_database):
    entity = stable_key("entity", "pump")
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.execute(
            insert(User).values(id=1, email="a@example.test", hashed_password="h")
        )
        connection.execute(insert(Charger).values(charger_id=entity))
        save_catalogue(connection, "pump")
        restore_entity_favorites(connection)
        # The former table allowed the same entity twice.
        connection.execute(
            text(
                "INSERT INTO favorites (user_id, charger_id) "
                "VALUES (1, :entity), (1, :entity)"
            ),
            {"entity": entity},
        )
        rewind_ledger(connection, "018_member_favorites.sql")
    with disposable_database.begin() as connection:
        assert apply_migrations(connection)["applied"] == migrations_from(
            "018_member_favorites.sql"
        )
        assert "favorites" not in inspect(connection).get_table_names()
        # Migration 023 then names the device behind the entity.
        assert connection.execute(
            text("SELECT user_id, kind, item_id FROM member_favorites")
        ).all() == [(1, "device", "pump")]


def test_device_favorites_migration_names_catalogue_devices(disposable_database):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.execute(
            insert(User).values(id=1, email="a@example.test", hashed_password="h")
        )
        connection.execute(
            text(
                "ALTER TABLE member_favorites DROP CONSTRAINT ck_member_favorite_kind;"
                "ALTER TABLE member_favorites ADD CONSTRAINT ck_member_favorite_kind "
                "CHECK (kind IN ('entity', 'reading', 'monitor'))"
            )
        )
        # An upgraded installation keeps recording the fan under its charger id.
        save_catalogue(
            connection,
            "pump",
            "fan",
            bindings={
                "fan:speed": {"entity_id": "charger-7", "device_id": "fan"},
                "outside": {"entity_id": stable_key("entity", "broker")},
            },
        )
        for kind, item_id in (
            ("entity", stable_key("entity", "pump")),
            ("entity", "charger-7"),
            # A broker's readings without a device, and an entity of no device.
            ("entity", stable_key("entity", "broker")),
            ("entity", "charger-9"),
            ("reading", "pump:flow"),
            ("monitor", "m1"),
        ):
            connection.execute(
                text(
                    "INSERT INTO member_favorites (user_id, kind, item_id) "
                    "VALUES (1, :kind, :item_id)"
                ),
                {"kind": kind, "item_id": item_id},
            )
        rewind_ledger(connection, "023_device_favorites.sql")
    with disposable_database.begin() as connection:
        assert apply_migrations(connection)["applied"] == migrations_from(
            "023_device_favorites.sql"
        )
        assert connection.execute(
            text("SELECT kind, item_id FROM member_favorites ORDER BY kind, item_id")
        ).all() == [
            ("device", "fan"),
            ("device", "pump"),
            ("monitor", "m1"),
            ("reading", "pump:flow"),
        ]
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO member_favorites (user_id, kind, item_id) "
                    "VALUES (1, 'entity', 'x')"
                )
            )


def test_member_roles_migration_keeps_every_members_access(disposable_database):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        restore_role_enum(connection)
        for id, role in ((1, "admin"), (2, "user")):
            connection.execute(
                insert(User).values(
                    id=id, email=f"{role}@example.test", hashed_password="h", role=role
                )
            )
        rewind_ledger(connection, "021_member_roles.sql")
    with disposable_database.begin() as connection:
        assert apply_migrations(connection)["applied"] == migrations_from(
            "021_member_roles.sql"
        )
        assert connection.execute(
            text("SELECT id, name, permissions FROM member_roles ORDER BY id")
        ).all() == [("admin", "Administrator", []), ("user", "Member", [])]
        assert connection.execute(
            text("SELECT id, role FROM users ORDER BY id")
        ).all() == [(1, "admin"), (2, "user")]
        schema = inspect(connection)
        assert [key["referred_table"] for key in schema.get_foreign_keys("users")] == [
            "member_roles"
        ]
        assert not connection.scalar(
            text("SELECT count(*) FROM pg_type WHERE typname = 'roleenum'")
        )
        # A role a member holds cannot disappear underneath them.
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(text("DELETE FROM member_roles WHERE id = 'user'"))


def test_run_timeline_migration_keeps_existing_runs(disposable_database):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.execute(text("DROP TABLE monitoring_pipeline_run_events"))
        connection.execute(
            text("ALTER TABLE monitoring_pipeline_runs DROP COLUMN final_status")
        )
        rewind_ledger(connection, "016_pipeline_run_events.sql")
        connection.execute(
            insert(PipelineRun).values(
                id="earlier",
                service_id="earlier-service",
                launch_config={},
                layout={},
                status="stopped",
            )
        )
    with disposable_database.begin() as connection:
        assert apply_migrations(connection)["applied"] == migrations_from(
            "016_pipeline_run_events.sql"
        )
        # Runs from before the timeline have no final status and no events.
        assert connection.execute(
            text(
                "SELECT status, final_status FROM monitoring_pipeline_runs "
                "WHERE id='earlier'"
            )
        ).one() == ("stopped", None)
        assert (
            connection.scalar(
                text("SELECT count(*) FROM monitoring_pipeline_run_events")
            )
            == 0
        )


def test_migrations_adopt_verified_baseline_preserve_data_and_repeat(
    disposable_database,
):
    with disposable_database.begin() as connection:
        assert migration_status(connection)["fresh"]
        apply_migrations(connection)
        assert migration_status(connection)["pending"] == []
        connection.execute(
            insert(MonitoringService).values(
                id="old",
                container_name="old",
                status=False,
                mqtt_topic=[],
            )
        )
        rewind_ledger(connection)
        connection.execute(text("DROP TABLE deployment_maintenance"))
        connection.execute(text("DROP TABLE remembered_sessions"))
        remove_pipeline_schema(connection)
        connection.execute(text("ALTER TABLE services DROP COLUMN launch_config"))
        for table in (
            "system_configuration",
            "system_revisions",
            "system_collection_configuration",
        ):
            connection.execute(text(f"DROP TABLE {table}"))
    with disposable_database.begin() as connection:
        assert migration_status(connection)["pending"] == migrations_from(
            "003_deployment_maintenance.sql"
        )
        assert apply_migrations(connection)["applied"] == migrations_from(
            "003_deployment_maintenance.sql"
        )
        assert (
            connection.scalar(text("SELECT count(*) FROM services WHERE id='old'")) == 1
        )
        assert apply_migrations(connection)["applied"] == []
        changed = migration_files() | {"003_deployment_maintenance.sql": "SELECT 1;"}
        with pytest.raises(ValueError, match="history differs"):
            migration_status(connection, changed)


@pytest.mark.parametrize("ledger", [False, True])
def test_clean_break_preserves_configuration_and_history_and_runs_once(
    disposable_database, ledger
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.execute(
            insert(MonitoringService).values(
                id="existing-service",
                container_name="existing-service",
                status=False,
                mqtt_topic=["telemetry/existing/temperature"],
                launch_config={
                    "display_name": "Existing monitor",
                    "training_window_size": 32,
                },
            )
        )
        connection.execute(
            insert(CollectionConfiguration).values(
                id=1,
                revision=7,
                document={
                    "sources": [],
                    "default_policy": {"mode": "off", "interval_seconds": 10},
                },
                ingress_status={},
                collection_status={},
                updated_by="operator",
            )
        )
        connection.execute(
            insert(Telemetry).values(
                charger_id="existing",
                timestamp=datetime.now(UTC),
                type="temperature",
                value=24.5,
                data_source="mqtt",
            )
        )
        for table in (
            "system_configuration",
            "system_revisions",
            "system_collection_configuration",
            "remembered_sessions",
        ):
            connection.execute(text(f"DROP TABLE {table}"))
        remove_pipeline_schema(connection)
        rewind_ledger(connection, "004_system_catalogue.sql" if ledger else None)
        if not ledger:
            restore_retired_schema(connection)
    with disposable_database.begin() as connection:
        assert migration_status(connection)["pending"] == migrations_from(
            "004_system_catalogue.sql"
        )
        assert apply_migrations(connection)["applied"] == migrations_from(
            "004_system_catalogue.sql"
        )
        assert (
            connection.scalar(
                text("SELECT revision FROM collection_configuration WHERE id=1")
            )
            == 7
        )
        assert (
            connection.scalar(
                text("SELECT value FROM telemetry WHERE charger_id='existing'")
            )
            == 24.5
        )
        assert connection.scalar(
            text("SELECT launch_config FROM services WHERE id='existing-service'")
        ) == {
            "display_name": "Existing monitor",
            "training_window_size": 32,
        }
        assert (
            connection.scalar(
                text("SELECT count(*) FROM system_collection_configuration")
            )
            == 1
        )
        assert connection.scalar(text("SELECT count(*) FROM system_configuration")) == 1
        assert not inspect(connection).has_table("model_registry")
        assert "stateful_set_name" not in {
            column["name"] for column in inspect(connection).get_columns("services")
        }
        connection.execute(
            insert(Telemetry).values(
                charger_id="existing",
                timestamp=datetime.now(UTC),
                type="temperature",
                value=30,
                data_source="mqtt",
            )
        )
        assert apply_migrations(connection)["applied"] == []
        assert sorted(
            connection.scalars(
                text("SELECT value FROM telemetry WHERE charger_id='existing'")
            )
        ) == [24.5, 30]


def test_failed_migration_rolls_back_ddl_and_ledger_and_lock_blocks_competitors(
    disposable_database,
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
    migrations = migration_files() | {
        "006_failure.sql": "CREATE TABLE release_probe (id integer); SELECT 1 / 0;"
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
    states = {"old-task": "running", "stopping-task": "running"}

    class Docker:
        client = SimpleNamespace(
            services=SimpleNamespace(
                get=lambda identifier: SimpleNamespace(
                    attrs={"Spec": {"Mode": {"Replicated": {"Replicas": 0}}}},
                    scale=lambda replicas: states.update(
                        {identifier + "-task": "shutdown"}
                    ),
                )
            ),
            api=SimpleNamespace(
                tasks=lambda **kw: [
                    {
                        "ID": kw["filters"]["service"] + "-task",
                        "Status": {"State": states[kw["filters"]["service"] + "-task"]},
                    }
                ],
                inspect_task=lambda task: {"Status": {"State": states[task]}},
            ),
        )

        async def run(self, function, *args, **kwargs):
            return function(*args, **kwargs)

    workloads = SimpleNamespace(async_docker=Docker())
    removed = []
    created = []

    async def remove(identifier):
        removed.append(identifier)
        states[identifier + "-task"] = "shutdown"
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
    monkeypatch.setattr(radar, "get_async_docker", Docker)
    monkeypatch.setattr(
        "aberration_tactic_middleware.services.orchestration.radar_environment."
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
            side_effect=[RuntimeError("Docker unavailable"), False]
        ),
        async_docker=SimpleNamespace(),
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
async def test_task_removal_requires_actual_shutdown(monkeypatch):
    monkeypatch.setattr(deployment.asyncio, "sleep", AsyncMock())
    service = SimpleNamespace(attrs={"Spec": {"Mode": {"Replicated": {"Replicas": 0}}}})
    get = MagicMock(return_value=service)
    tasks = MagicMock(return_value=[{"Status": {"State": "running"}}])
    workloads = SimpleNamespace(
        async_docker=SimpleNamespace(
            client=SimpleNamespace(
                services=SimpleNamespace(get=get),
                api=SimpleNamespace(tasks=tasks),
            ),
            run=AsyncMock(
                side_effect=lambda function, *args, **kwargs: function(*args, **kwargs)
            ),
        )
    )
    with pytest.raises(ValueError, match="did not stop"):
        await deployment.wait_stopped(workloads, "service", attempts=1)
    tasks.return_value = [{"Status": {"State": "shutdown"}}]
    await deployment.wait_stopped(workloads, "service", attempts=1)
    # Cancelled tasks can disappear without being retained in Swarm history.
    tasks.return_value = []
    await deployment.wait_stopped(workloads, "service", attempts=1)
    service.attrs["Spec"]["Mode"]["Replicated"]["Replicas"] = 1
    with pytest.raises(ValueError, match="zero replicas"):
        await deployment.wait_stopped(workloads, "service", attempts=1)
    get.side_effect = docker.errors.NotFound("missing service")
    with pytest.raises(ValueError, match="recovery is required"):
        await deployment.wait_stopped(workloads, "service", attempts=1)


def test_maintenance_docker_socket_url_has_no_tcp_port():
    from aberration_tactic_middleware.config.config import DockerConfig

    assert (
        DockerConfig(api_url="unix:///var/run/docker.sock").base_url
        == "unix:///var/run/docker.sock"
    )


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
