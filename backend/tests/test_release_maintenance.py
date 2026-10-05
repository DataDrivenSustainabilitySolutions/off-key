"""Verify release locking, retries and migration transactions in isolated databases."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_core.db.collection import lock_collection_configuration
from off_key_core.db.maintenance import (
    DeploymentInProgressError,
    require_application_writes,
)
from off_key_core.db.migrate import (
    MIGRATION_LOCK,
    apply_migrations,
    migration_files,
    migration_status,
)
from off_key_core.db.models import (
    DeploymentMaintenance,
    MonitoringEvidence,
    MonitoringService,
)
from off_key_core.schemas.radar import RadarStartConfig
from off_key_tactic_middleware import deployment
from off_key_tactic_middleware.services.orchestration import radar
from off_key_tactic_middleware.services.orchestration.radar import (
    RadarOrchestrationService,
)
from sqlalchemy import insert, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


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
        connection.execute(text("DROP TABLE off_key_schema_migrations"))
        connection.execute(text("DROP TABLE deployment_maintenance"))
        connection.execute(text("ALTER TABLE services DROP COLUMN launch_config"))
    with disposable_database.begin() as connection:
        assert migration_status(connection)["pending"] == [
            "003_deployment_maintenance.sql"
        ]
        assert apply_migrations(connection)["applied"] == [
            "003_deployment_maintenance.sql"
        ]
        assert (
            connection.scalar(text("SELECT count(*) FROM services WHERE id='old'")) == 1
        )
        assert apply_migrations(connection)["applied"] == []
        changed = migration_files() | {"003_deployment_maintenance.sql": "SELECT 1;"}
        with pytest.raises(ValueError, match="history differs"):
            migration_status(connection, changed)


def test_failed_migration_rolls_back_ddl_and_ledger_and_lock_blocks_competitors(
    disposable_database,
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
    migrations = migration_files() | {
        "004_failure.sql": "CREATE TABLE release_probe (id integer); SELECT 1 / 0;"
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
async def test_monitor_cutover_blocks_writes_preserves_intent_and_resumes_once(
    disposable_database, monkeypatch
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    revision = "a" * 40
    config = RadarStartConfig(
        container_name="first",
        mqtt_topics=["device/evCharger/charger-1/sine"],
        model_type="pyod_iforest",
    )
    config2 = config.model_copy(update={"container_name": "stopping"})
    states = {"old-task": "running", "stopping-task": "running"}

    class Docker:
        client = SimpleNamespace(
            services=SimpleNamespace(
                get=lambda identifier: SimpleNamespace(
                    scale=lambda replicas: states.update(
                        {identifier + "-task": "shutdown"}
                    ),
                )
            ),
            api=SimpleNamespace(
                tasks=lambda **kw: [
                    {
                        "ID": kw["filters"]["service"] + "-task",
                        "Status": {"State": "running"},
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
    workloads.validate_started = AsyncMock()
    workloads.remove_after_failure = AsyncMock()
    workloads.get_status_and_labels = AsyncMock(return_value=("running", {}))
    snapshot = SimpleNamespace(
        revision=1,
        collection={"revision": 1, "status": "applied"},
        catalog=SimpleNamespace(
            streams=lambda **kw: [
                SimpleNamespace(
                    accepted_topic=config.mqtt_topics[0],
                    sensor=SimpleNamespace(value_type="number"),
                    signature=("fixture",),
                )
            ],
        ),
    )
    monkeypatch.setattr(
        radar, "read_collection_configuration", AsyncMock(return_value=snapshot)
    )
    monkeypatch.setattr(radar, "get_async_docker", Docker)
    registry = MagicMock()
    registry.validate_model_params.return_value = {}
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
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
            orchestration = RadarOrchestrationService(session, registry)
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
async def test_task_removal_requires_actual_shutdown(monkeypatch):
    monkeypatch.setattr(deployment.asyncio, "sleep", AsyncMock())
    workloads = SimpleNamespace(
        async_docker=SimpleNamespace(
            client=SimpleNamespace(
                api=SimpleNamespace(
                    inspect_task=lambda task: {"Status": {"State": "running"}}
                )
            ),
            run=AsyncMock(return_value={"Status": {"State": "running"}}),
        )
    )
    with pytest.raises(ValueError, match="did not stop"):
        await deployment.wait_stopped(workloads, ["task"], attempts=1)
    workloads.async_docker.run.assert_awaited_once()


def test_maintenance_docker_socket_url_has_no_tcp_port():
    from off_key_tactic_middleware.config.config import DockerConfig

    assert (
        DockerConfig(api_url="unix:///var/run/docker.sock").base_url
        == "unix:///var/run/docker.sock"
    )
