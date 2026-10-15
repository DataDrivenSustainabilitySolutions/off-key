"""Durable RADAR intent and real Swarm adoption after controller interruption."""

import asyncio
import os
import time
from contextlib import suppress
from datetime import UTC, datetime
from uuid import uuid4

import docker
import pytest
import pytest_asyncio
from off_key_core.db.collection import lock_collection_configuration
from off_key_core.db.migrate import apply_migrations
from off_key_core.db.models import MonitoringService
from off_key_core.schemas.collection_policy import CollectionPolicy
from off_key_core.schemas.radar import RadarStartConfig
from off_key_core.schemas.system import SystemChange
from off_key_core.schemas.system_collection import SystemCollectionChange
from off_key_mqtt_radar.admission import (
    RadarAdmissionSettings,
    require_monitor_admission,
)
from off_key_tactic_middleware.config.config import DockerConfig
from off_key_tactic_middleware.config.system_live import SystemLiveSettings
from off_key_tactic_middleware.domain import ConflictError
from off_key_tactic_middleware.facades.docker import AsyncDocker
from off_key_tactic_middleware.services import collection_monitors, system_collection
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
from off_key_tactic_middleware.services.reconciliation import (
    RadarStatusReconciliationService,
)
from off_key_tactic_middleware.services.system import SystemService
from off_key_tactic_middleware.services.system_collection import SystemCollectionService
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


async def pending_monitor(sessions, workloads, owned, *, command=None):
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
        command=command or ["/bin/sh", "-c", "sleep 120"],
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


@pytest.mark.asyncio
async def test_reconciliation_docker_latency_does_not_block_or_overwrite_heartbeat(
    lifecycle_database,
    swarm_workloads,
):
    sessions = lifecycle_database
    workloads, owned = swarm_workloads
    service_id, _ = await pending_monitor(sessions, workloads, owned)
    async with sessions() as session:
        await RadarLifecycleController(session, workloads).complete_creation(service_id)
    async with sessions.begin() as session:
        await session.execute(
            update(MonitoringService)
            .where(MonitoringService.id == service_id)
            .values(status=False, operational_stage="failed")
        )
    reconciler = RadarStatusReconciliationService.__new__(
        RadarStatusReconciliationService
    )
    reconciler.async_docker = workloads.async_docker
    reconciler.terminal_service_retention_hours = 24
    entered, release = asyncio.Event(), asyncio.Event()
    probe = reconciler._get_docker_status

    async def delayed_probe(workload_id):
        entered.set()
        await release.wait()
        return await probe(workload_id)

    reconciler._get_docker_status = delayed_probe
    async with sessions() as session:
        task = asyncio.create_task(reconciler._reconcile_with_session(session))
        await asyncio.wait_for(entered.wait(), 10)
        heartbeat = datetime.now(UTC)
        payload = {
            "stage": "operational",
            "processed_message_count": 123,
            "is_stale": False,
        }
        try:
            async with asyncio.timeout(2), sessions.begin() as writer:
                await writer.execute(
                    update(MonitoringService)
                    .where(MonitoringService.id == service_id)
                    .values(
                        operational_stage="operational",
                        operational_status=payload,
                        operational_updated_at=heartbeat,
                    )
                )
        finally:
            release.set()
        await task
    async with sessions() as session:
        current = await session.get(MonitoringService, service_id)
        assert current.status
        assert current.operational_status == payload
        assert current.operational_updated_at == heartbeat
    # A concurrent stop changes the generation while the next Docker read is
    # pending. Its old running observation must not revive or overwrite intent.
    entered.clear()
    release.clear()
    async with sessions() as session:
        task = asyncio.create_task(reconciler._reconcile_with_session(session))
        await asyncio.wait_for(entered.wait(), 10)
        try:
            async with sessions.begin() as writer:
                await writer.execute(
                    update(MonitoringService)
                    .where(MonitoringService.id == service_id)
                    .values(
                        desired_state="stopped",
                        lifecycle_version=MonitoringService.lifecycle_version + 1,
                        stop_requested_at=datetime.now(UTC),
                    )
                )
        finally:
            release.set()
        await task
    async with sessions() as session:
        current = await session.get(MonitoringService, service_id)
        assert (
            current.desired_state == "stopped" and current.stop_requested_at is not None
        )
        assert current.operational_status == payload


@pytest.mark.asyncio
async def test_delete_holds_claim_until_real_swarm_task_stops_without_database_lock(
    lifecycle_database,
    swarm_workloads,
    monkeypatch,
):
    sessions = lifecycle_database
    workloads, owned = swarm_workloads
    service_id, workload = await pending_monitor(
        sessions,
        workloads,
        owned,
        command=[
            "/bin/sh",
            "-c",
            'trap "sleep 2; exit 0" TERM; while true; do sleep 0.1; done',
        ],
    )
    async with sessions() as session:
        await RadarLifecycleController(session, workloads).complete_creation(service_id)
    monkeypatch.setattr(
        radar_module, "get_async_docker", lambda: workloads.async_docker
    )
    async with sessions() as session:
        service = radar_module.RadarOrchestrationService(session, None)
        started = time.monotonic()
        deleting = asyncio.create_task(service.delete_radar_service(service_id))
        async with asyncio.timeout(10):
            while True:
                await workloads.async_docker.run(workload.reload)
                if workload.attrs["Spec"]["Mode"]["Replicated"]["Replicas"] == 0:
                    break
                await asyncio.sleep(0.01)
        async with asyncio.timeout(1), sessions.begin() as concurrent:
            await lock_collection_configuration(concurrent)
            row = await concurrent.get(MonitoringService, service_id)
            assert row is not None and row.status and row.desired_state == "deleted"
            row.operational_updated_at = datetime.now(UTC)
        assert await deleting
        assert time.monotonic() - started >= 1.5
    async with sessions() as session:
        assert await session.get(MonitoringService, service_id) is None


@pytest.mark.asyncio
async def test_externally_removed_service_retains_claim_while_real_tasks_retire(
    lifecycle_database,
    swarm_workloads,
    monkeypatch,
):
    sessions = lifecycle_database
    workloads, owned = swarm_workloads
    service_id, workload = await pending_monitor(
        sessions,
        workloads,
        owned,
        command=[
            "/bin/sh",
            "-c",
            'trap "sleep 2; exit 0" TERM; while true; do sleep 0.1; done',
        ],
    )
    async with sessions() as session:
        await RadarLifecycleController(session, workloads).complete_creation(service_id)
    await workloads.async_docker.run(workload.remove)
    remaining = await workloads._remaining_service_tasks(workload.id)
    assert any(task["Status"]["State"] == "running" for task in remaining)
    monkeypatch.setattr(
        radar_module, "get_async_docker", lambda: workloads.async_docker
    )
    async with sessions() as session:
        service = radar_module.RadarOrchestrationService(session, None)
        started = time.monotonic()
        deleting = asyncio.create_task(service.delete_radar_service(service_id))
        await asyncio.sleep(0.1)
        async with sessions() as observer:
            row = await observer.get(MonitoringService, service_id)
            assert row is not None and row.status
        assert await deleting
        assert time.monotonic() - started >= 1.5


@pytest.mark.asyncio
async def test_collection_edit_revalidates_revision_after_unlocked_real_docker_stop(
    lifecycle_database,
    swarm_workloads,
    monkeypatch,
):
    from .test_system_configuration import document

    sessions = lifecycle_database
    workloads, owned = swarm_workloads
    monkeypatch.setattr(
        collection_monitors, "get_async_session_local", lambda: sessions
    )
    monkeypatch.setattr(
        collection_monitors, "get_async_docker", lambda: workloads.async_docker
    )
    monkeypatch.setattr(
        system_collection,
        "get_system_live_settings",
        lambda: SystemLiveSettings(SYSTEM_LIVE_ALLOWED_HOSTS=["localhost"]),
    )
    async with sessions() as session:
        saved = await SystemService(session).save(
            SystemChange(expected_revision=0, document=document()), actor="review"
        )
        saved = await SystemCollectionService(session).apply(
            SystemCollectionChange(
                expected_revision=saved.revision,
                expected_collection_revision=saved.runtime.collection_revision,
                stream_ids=["temperature-1"],
                policy=CollectionPolicy(mode="original"),
            ),
            actor="review",
        )
        await session.commit()
    service_id, _ = await pending_monitor(sessions, workloads, owned)
    async with sessions() as session:
        await RadarLifecycleController(session, workloads).complete_creation(service_id)
    async with sessions.begin() as session:
        await session.execute(
            update(MonitoringService)
            .where(MonitoringService.id == service_id)
            .values(
                mqtt_topic=[saved.runtime.bindings["temperature-1"]["accepted_topic"]]
            )
        )
    entered, release = asyncio.Event(), asyncio.Event()
    original_run = workloads.async_docker.run

    async def delayed_docker(function, *args, **kwargs):
        result = await original_run(function, *args, **kwargs)
        if getattr(function, "__name__", "") == "scale":
            entered.set()
            await release.wait()
        return result

    workloads.async_docker.run = delayed_docker
    edit = saved.document.model_copy(deep=True)
    edit.streams[0].payload_pointer = "/changed"

    async def change_inputs():
        async with sessions() as session:
            try:
                result = await SystemService(session).save(
                    SystemChange(
                        expected_revision=saved.revision,
                        document=edit,
                        pause_affected_monitors=True,
                    ),
                    actor="first",
                )
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise

    task = asyncio.create_task(change_inputs())
    await asyncio.wait_for(entered.wait(), 10)
    try:
        async with asyncio.timeout(2), sessions() as session:
            latest = await SystemService(session).read()
            renamed = latest.document.model_copy(deep=True)
            renamed.label = "Concurrent save"
            await SystemService(session).save(
                SystemChange(expected_revision=latest.revision, document=renamed),
                actor="second",
            )
            await session.commit()
    finally:
        release.set()
    with pytest.raises(ConflictError, match="changed while monitors stopped"):
        await task
    async with sessions() as session:
        latest = await SystemService(session).read()
        monitor = await session.get(MonitoringService, service_id)
        assert latest.document.label == "Concurrent save"
        assert latest.document.streams[0].payload_pointer != "/changed"
        assert not monitor.status and monitor.desired_state == "stopped"
