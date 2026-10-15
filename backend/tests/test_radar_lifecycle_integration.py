"""Durable RADAR intent and real Swarm adoption after controller interruption."""

import asyncio
import os
from contextlib import suppress
from uuid import uuid4

import docker
import pytest
import pytest_asyncio
from off_key_core.db.migrate import apply_migrations
from off_key_core.db.models import MonitoringService
from off_key_core.schemas.radar import RadarStartConfig
from off_key_mqtt_radar.admission import (
    RadarAdmissionSettings,
    require_monitor_admission,
)
from off_key_tactic_middleware.config.config import DockerConfig
from off_key_tactic_middleware.facades.docker import AsyncDocker
from off_key_tactic_middleware.services.orchestration import radar as radar_module
from off_key_tactic_middleware.services.orchestration.radar_environment import (
    build_radar_config_fingerprint,
    build_radar_environment,
    build_radar_workload_labels,
)
from off_key_tactic_middleware.services.orchestration.radar_lifecycle import (
    RadarLifecycleController,
)
from off_key_tactic_middleware.services.orchestration.radar_workloads import (
    RadarWorkloadManager,
)
from sqlalchemy import delete, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def lifecycle_database(disposable_database):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def swarm_workloads():
    if os.getenv("TEST_RADAR_DOCKER") != "1":
        pytest.skip("Set TEST_RADAR_DOCKER=1 for isolated real Swarm lifecycle tests")
    client = docker.from_env()
    if not client.info().get("Swarm", {}).get("ControlAvailable"):
        pytest.skip("Requires the disposable Docker engine to be a Swarm manager")
    # Use the production facade with an explicitly injected real local engine.
    # This bypasses only the deployed TCP proxy address, not Docker operations.
    facade = AsyncDocker.__new__(AsyncDocker)
    facade.client = client
    facade.config = DockerConfig()
    facade.semaphore = asyncio.Semaphore(5)
    workloads = RadarWorkloadManager(facade)
    owned = []
    try:
        yield workloads, owned
    finally:
        for service in owned:
            with suppress(docker.errors.NotFound):
                await facade.run(service.remove)
        client.close()


async def pending_monitor(sessions, workloads, owned):
    service_id = str(uuid4())
    config = RadarStartConfig(
        container_name="review-" + service_id, mqtt_topics=["telemetry/entity/value"]
    )
    environment = build_radar_environment(
        service_id=service_id, config=config, model_registry=None
    )
    environment["RADAR_COLLECTION_FINGERPRINT"] = "review-collection"
    environment["RADAR_LIFECYCLE_VERSION"] = "1"
    async with sessions.begin() as session:
        session.add(
            MonitoringService(
                id=service_id,
                container_name=config.container_name,
                mqtt_topic=config.mqtt_topics,
                status=True,
                desired_state="running",
                lifecycle_version=1,
                launch_config=config.model_dump(mode="json"),
                config_fingerprint=build_radar_config_fingerprint(environment),
                collection_fingerprint="review-collection",
                operational_stage="starting",
            )
        )
    # A real external create can finish even though the requesting controller
    # dies before binding its ID. The fixture process just occupies that worker.
    labels = build_radar_workload_labels(environment, "eclipse-mosquitto:2.0") | {
        "off-key.review": "radar-fixes"
    }
    workload = await workloads.async_docker.run(
        workloads.async_docker.client.services.create,
        "eclipse-mosquitto:2.0",
        name="radar-" + service_id,
        command=["/bin/sh", "-c", "sleep 120"],
        labels=labels,
        env=environment,
        restart_policy={"Condition": "none"},
    )
    owned.append(workload)
    return service_id, workload


@pytest.mark.asyncio
async def test_cancelled_creation_is_adopted_once_and_keeps_sensor_claim(
    lifecycle_database, swarm_workloads, monkeypatch
):
    sessions = lifecycle_database
    workloads, owned = swarm_workloads
    service_id, workload = await pending_monitor(sessions, workloads, owned)
    entered_validation = asyncio.Event()
    original_validation = workloads.validate_started

    async def await_interruption(remote):
        assert remote.id == workload.id
        entered_validation.set()
        await asyncio.Event().wait()

    # Coordinate interruption after the real Docker read, without replacing
    # storage, Docker lookup, workload identity or worker ownership operations.
    workloads.validate_started = await_interruption
    async with sessions() as session:
        creation = asyncio.create_task(
            RadarLifecycleController(session, workloads).complete_creation(service_id)
        )
        await asyncio.wait_for(entered_validation.wait(), 10)
        creation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await creation
    workloads.validate_started = original_validation
    async with sessions() as session:
        pending = await session.get(MonitoringService, service_id)
        assert pending.container_id is None and pending.status
        monkeypatch.setattr(
            radar_module, "get_async_docker", lambda: workloads.async_docker
        )
        orchestration = radar_module.RadarOrchestrationService(session, None)
        with pytest.raises(ValueError, match="overlaps active service"):
            await orchestration._assert_topics_available(
                mqtt_topics=["telemetry/entity/value"], container_name="another"
            )
        await session.rollback()

    async def recover():
        async with sessions() as session:
            return await RadarLifecycleController(session, workloads).complete_creation(
                service_id
            )

    first, second = await asyncio.gather(recover(), recover())
    assert first.container_id == second.container_id == workload.id
    services = await workloads.async_docker.run(
        workloads.async_docker.client.services.list,
        filters={"name": "radar-" + service_id},
    )
    assert [service.id for service in services] == [workload.id]


@pytest.mark.asyncio
async def test_deleted_intent_fences_late_worker_and_orphan_cleanup(
    lifecycle_database, swarm_workloads
):
    sessions = lifecycle_database
    workloads, owned = swarm_workloads
    service_id, _workload = await pending_monitor(sessions, workloads, owned)
    other_id, other_workload = await pending_monitor(sessions, workloads, owned)
    await workloads.async_docker.run(
        other_workload.update,
        labels=other_workload.attrs["Spec"]["Labels"]
        | {"radar_controller_id": "other-deployment"},
    )
    settings = RadarAdmissionSettings(SERVICE_ID=service_id, RADAR_LIFECYCLE_VERSION=1)
    await require_monitor_admission(settings=settings, session_factory=sessions)
    async with sessions.begin() as session:
        await session.execute(
            update(MonitoringService)
            .where(MonitoringService.id == service_id)
            .values(desired_state="deleted", lifecycle_version=2)
        )
    with pytest.raises(RuntimeError, match="no longer owns"):
        await require_monitor_admission(settings=settings, session_factory=sessions)
    async with sessions.begin() as session:
        await session.execute(
            delete(MonitoringService).where(
                MonitoringService.id.in_([service_id, other_id])
            )
        )
    with pytest.raises(RuntimeError, match="no longer owns"):
        await require_monitor_admission(settings=settings, session_factory=sessions)
    async with sessions() as session:
        await RadarLifecycleController(session, workloads).remove_orphans()
    assert await workloads.find(service_id) is None
    assert (await workloads.find(other_id)).id == other_workload.id


@pytest.mark.asyncio
async def test_admission_rejects_stale_generation_and_collection_stop(
    lifecycle_database,
):
    sessions = lifecycle_database
    async with sessions.begin() as session:
        session.add(
            MonitoringService(
                id="generation",
                container_name="generation",
                mqtt_topic=[],
                status=True,
                lifecycle_version=2,
                desired_state="running",
            )
        )
    with pytest.raises(RuntimeError, match="no longer owns"):
        await require_monitor_admission(
            settings=RadarAdmissionSettings(
                SERVICE_ID="generation", RADAR_LIFECYCLE_VERSION=1
            ),
            session_factory=sessions,
        )
    await require_monitor_admission(
        settings=RadarAdmissionSettings(
            SERVICE_ID="generation", RADAR_LIFECYCLE_VERSION=2
        ),
        session_factory=sessions,
    )
    async with sessions.begin() as session:
        await session.execute(
            update(MonitoringService)
            .where(MonitoringService.id == "generation")
            .values(desired_state="stopped")
        )
    with pytest.raises(RuntimeError, match="no longer owns"):
        await require_monitor_admission(
            settings=RadarAdmissionSettings(
                SERVICE_ID="generation", RADAR_LIFECYCLE_VERSION=2
            ),
            session_factory=sessions,
        )


@pytest.mark.asyncio
async def test_pending_configuration_failure_is_visible_without_releasing_claim(
    lifecycle_database,
):
    sessions = lifecycle_database
    config = RadarStartConfig(
        container_name="failed", mqtt_topics=["telemetry/entity/value"]
    )
    async with sessions.begin() as session:
        session.add(
            MonitoringService(
                id="failed",
                container_name="failed",
                mqtt_topic=config.mqtt_topics,
                desired_state="running",
                status=True,
                lifecycle_version=1,
                launch_config=config.model_dump(mode="json"),
                config_fingerprint="obsolete",
            )
        )
    async with sessions() as session:
        with pytest.raises(RuntimeError, match="differs from this runtime"):
            await RadarLifecycleController(session, None).complete_creation("failed")
        monitor = await session.get(MonitoringService, "failed", populate_existing=True)
        assert monitor.status and monitor.desired_state == "running"
        assert monitor.container_id is None
        assert monitor.operational_stage == "failed"
        assert monitor.operational_status["error"] == "RuntimeError"


@pytest.mark.parametrize("ledger", [True, False])
def test_lifecycle_migration_adopts_existing_attached_and_stopped_rows(
    disposable_database, ledger
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.execute(
            text("""
            INSERT INTO services (id, container_id, container_name, mqtt_topic,
                status, operational_stage, operational_status)
            VALUES ('active', 'attached', 'active', '[]', true, 'starting', '{}'),
                   ('inactive', null, 'inactive', '[]', false, 'stopped', '{}');
            ALTER TABLE services DROP COLUMN desired_state;
            ALTER TABLE services DROP COLUMN lifecycle_version;
            ALTER TABLE services DROP COLUMN config_fingerprint;
            ALTER TABLE services DROP COLUMN collection_fingerprint;
        """)
        )
        if ledger:
            connection.execute(
                text(
                    "DELETE FROM off_key_schema_migrations "
                    "WHERE version = '009_radar_lifecycle_intent.sql'"
                )
            )
        else:
            connection.execute(text("DROP TABLE off_key_schema_migrations"))
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        assert connection.execute(
            text(
                "SELECT id, desired_state, lifecycle_version, container_id "
                "FROM services ORDER BY id"
            )
        ).all() == [
            ("active", "running", 1, "attached"),
            ("inactive", "stopped", 1, None),
        ]
