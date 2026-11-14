"""Durable RADAR intent and real pool adoption after controller interruption."""

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from off_key_core.db.collection import lock_collection_configuration
from off_key_core.db.migrate import apply_migrations
from off_key_core.db.models import MonitoringService
from off_key_core.db.workloads import RadarWorkload
from off_key_core.schemas.collection_policy import CollectionPolicy
from off_key_core.schemas.system import SystemChange
from off_key_core.schemas.system_collection import SystemCollectionChange
from off_key_mqtt_radar.admission import (
    RadarAdmissionSettings,
    require_monitor_admission,
)
from off_key_tactic_middleware.config.system_live import SystemLiveSettings
from off_key_tactic_middleware.domain import ConflictError
from off_key_tactic_middleware.services.catalogue import system_collection
from off_key_tactic_middleware.services.catalogue.system import SystemService
from off_key_tactic_middleware.services.orchestration import (
    collection_monitors,
    radar_workloads,
)
from off_key_tactic_middleware.services.orchestration import radar as radar_module
from off_key_tactic_middleware.services.orchestration.radar_environment import (
    build_radar_config_fingerprint,
    build_radar_environment,
    build_radar_workload_labels,
)
from off_key_tactic_middleware.services.orchestration.radar_lifecycle import (
    RadarLifecycleController,
)
from off_key_tactic_middleware.services.orchestration.radar_queries import (
    RadarServiceQueries,
)
from off_key_tactic_middleware.services.orchestration.radar_workloads import (
    RadarWorkloadManager,
)
from off_key_tactic_middleware.services.orchestration.reconciliation import (
    RadarStatusReconciliationService,
)
from off_key_tactic_middleware.services.orchestration.workload_identity import (
    radar_workload_name,
)
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.support.env import DATABASE_ENVIRONMENT, set_environment
from tests.support.form_pipeline import form_launch
from tests.support.radar_pool import RUNTIME, running_pool

# A runtime no replica runs: its workloads wait for room, as on a full pool.
ELSEWHERE = "registry/radar:elsewhere"
# Each child runs the code its row names, so one pool serves every scenario.
CHILD = "import os, time; exec(os.environ.get('FIXTURE_CODE') or 'time.sleep(120)')"
# A child that takes two seconds to end after SIGTERM, like RADAR flushing.
SLOW_STOP = """
import signal, sys, time
signal.signal(signal.SIGTERM, lambda *_: (time.sleep(2), sys.exit(0)))
time.sleep(120)
"""


@pytest.fixture(autouse=True)
def database_environment(monkeypatch):
    set_environment(monkeypatch, DATABASE_ENVIRONMENT)
    monkeypatch.setenv("TACTIC_RADAR_IMAGE", RUNTIME)
    monkeypatch.setenv("TACTIC_RADAR_STARTUP_GRACE_SECONDS", "0.2")


@pytest_asyncio.fixture
async def lifecycle_engine(disposable_database):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def lifecycle_database(lifecycle_engine):
    return async_sessionmaker(lifecycle_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def pool_workloads(lifecycle_engine, lifecycle_database, monkeypatch):
    """A real pool replica, and every RadarWorkloadManager reading its table."""
    monkeypatch.setattr(
        radar_workloads, "get_async_session_local", lambda: lifecycle_database
    )
    async with running_pool(
        lifecycle_engine, code=CHILD, max_restarts=1, stop_timeout_seconds=10
    ) as pool:
        yield RadarWorkloadManager(), pool


async def pending_monitor(sessions, workloads, *, code=None, runtime=RUNTIME):
    service_id = str(uuid4())
    config = form_launch(
        container_name="review-" + service_id, mqtt_topics=["telemetry/entity/value"]
    )
    environment = build_radar_environment(
        service_id=service_id, config=config, validate_params=False
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
    # A create can finish even though the requesting controller dies before
    # binding its id: the row exists and the pool runs it.
    workload = await workloads.submit(
        name=radar_workload_name(service_id),
        kind="monitor",
        module="off_key_mqtt_radar",
        runtime=runtime,
        environment=environment | ({"FIXTURE_CODE": code} if code else {}),
        labels=build_radar_workload_labels(environment, runtime),
        restart=True,
    )
    return service_id, workload


async def wait_for_workload_state(workloads, workload, expected):
    state = None
    try:
        async with asyncio.timeout(30):
            while True:
                state, _ = await workloads.get_status_and_labels(workload.id)
                if state == expected:
                    return
                await asyncio.sleep(0.05)
    except TimeoutError:
        pytest.fail(
            f"RADAR workload {workload.id}: expected {expected!r}, last {state!r}",
            pytrace=False,
        )


async def running_monitor(sessions, workloads, *, code=None):
    service_id, workload = await pending_monitor(sessions, workloads, code=code)
    async with sessions() as session:
        await RadarLifecycleController(session, workloads).complete_creation(service_id)
    await wait_for_workload_state(workloads, workload, "running")
    return service_id, workload


async def kill_child(pool, workload):
    """End a running child the way the kernel's OOM killer would."""
    pool.children[workload.id].process.kill()


async def set_runtime(sessions, workload, runtime):
    async with sessions.begin() as session:
        await session.execute(
            update(RadarWorkload)
            .where(RadarWorkload.id == workload.id)
            .values(runtime=runtime)
        )


FAILED_TASK = {"stage": "failed", "detail": "Previous task failed"}


async def record_operational_status(sessions, service_id, stage, payload, **values):
    """Persist a runtime heartbeat the way RADAR does and return its timestamp."""
    heartbeat = datetime.now(UTC)
    async with sessions.begin() as session:
        await session.execute(
            update(MonitoringService)
            .where(MonitoringService.id == service_id)
            .values(
                operational_stage=stage,
                operational_status=payload,
                operational_updated_at=heartbeat,
                **values,
            )
        )
    return heartbeat


@asynccontextmanager
async def paused_reconciliation(reconciler, sessions, monkeypatch):
    """Hold a real workload observation until the concurrent write commits."""
    entered, release = asyncio.Event(), asyncio.Event()
    observations = {}
    probe = reconciler.workloads.statuses_and_labels

    async def delayed_probe(workload_ids):
        found = await probe(workload_ids)
        observations.update(
            (workload_id, state)
            for workload_id, (state, _) in zip(workload_ids, found, strict=True)
            if workload_id
        )
        entered.set()
        await release.wait()
        return found

    with monkeypatch.context() as patch:
        patch.setattr(reconciler.workloads, "statuses_and_labels", delayed_probe)
        async with sessions() as session:
            task = asyncio.create_task(reconciler._reconcile_with_session(session))
            try:
                await asyncio.wait_for(entered.wait(), 10)
                yield observations
            finally:
                release.set()
                await asyncio.wait_for(task, 10)


@pytest.mark.asyncio
async def test_cancelled_creation_is_adopted_once_and_keeps_sensor_claim(
    lifecycle_database, pool_workloads
):
    sessions = lifecycle_database
    workloads, _ = pool_workloads
    service_id, workload = await pending_monitor(sessions, workloads)
    entered_validation = asyncio.Event()
    original_validation = workloads.validate_started

    async def await_interruption(remote):
        assert remote.id == workload.id
        entered_validation.set()
        await asyncio.Event().wait()

    # Interrupt after the real row was read, replacing no storage, lookup,
    # identity or worker ownership operation.
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
        orchestration = radar_module.RadarOrchestrationService(session)
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
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count()).where(
                    RadarWorkload.name == radar_workload_name(service_id)
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_deleted_intent_fences_late_worker_and_orphan_cleanup(
    lifecycle_database, pool_workloads
):
    sessions = lifecycle_database
    workloads, _ = pool_workloads
    service_id, workload = await pending_monitor(sessions, workloads)
    other_id, other_workload = await pending_monitor(sessions, workloads)
    async with sessions.begin() as session:
        for monitor_id, row in ((service_id, workload), (other_id, other_workload)):
            monitor = await session.get(MonitoringService, monitor_id)
            monitor.container_id = row.id
    async with sessions() as session:
        overview = await RadarServiceQueries(session, workloads).list(
            include_workload_status=True
        )
        assert {item["id"] for item in overview} == {service_id, other_id}
        assert all(item["model_type"] == "pyod_iforest" for item in overview)
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
            delete(MonitoringService).where(MonitoringService.id == service_id)
        )
    with pytest.raises(RuntimeError, match="no longer owns"):
        await require_monitor_admission(settings=settings, session_factory=sessions)
    async with sessions() as session:
        await RadarLifecycleController(session, workloads).remove_orphans()
    assert await workloads.find(service_id) is None
    # A monitor that still runs keeps its workload.
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
    config = form_launch(
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


@pytest.mark.asyncio
@pytest.mark.parametrize("workload_state", ["pending", "running", "failed"])
async def test_reconciliation_latency_does_not_block_or_overwrite_heartbeat(
    lifecycle_database,
    pool_workloads,
    monkeypatch,
    workload_state,
):
    sessions = lifecycle_database
    workloads, pool = pool_workloads
    service_id, workload = await pending_monitor(
        sessions,
        workloads,
        runtime=ELSEWHERE if workload_state == "pending" else RUNTIME,
    )
    async with sessions() as session:
        await RadarLifecycleController(session, workloads).complete_creation(service_id)
    if workload_state == "failed":
        await wait_for_workload_state(workloads, workload, "running")
        await kill_child(pool, workload)
    await wait_for_workload_state(workloads, workload, workload_state)
    reconciler = RadarStatusReconciliationService(workloads=workloads)
    payload = {
        "stage": "operational",
        "processed_message_count": 123,
        "is_stale": False,
    }
    async with paused_reconciliation(reconciler, sessions, monkeypatch) as observations:
        assert observations == {workload.id: workload_state}
        async with asyncio.timeout(2):
            heartbeat = await record_operational_status(
                sessions, service_id, "operational", payload
            )
    async with sessions() as session:
        current = await session.get(MonitoringService, service_id)
        assert current.status, observations
        assert current.operational_stage == "operational"
        assert current.operational_status == payload
        assert current.operational_updated_at == heartbeat


@pytest.mark.asyncio
async def test_reconciliation_revives_inactive_monitor_only_once_the_pool_runs_it(
    lifecycle_database, pool_workloads
):
    sessions = lifecycle_database
    workloads, _ = pool_workloads
    service_id, workload = await pending_monitor(sessions, workloads, runtime=ELSEWHERE)
    async with sessions() as session:
        await RadarLifecycleController(session, workloads).complete_creation(service_id)
    await wait_for_workload_state(workloads, workload, "pending")
    heartbeat = await record_operational_status(
        sessions, service_id, "failed", FAILED_TASK, status=False
    )
    reconciler = RadarStatusReconciliationService(workloads=workloads)
    async with sessions() as session:
        await reconciler._reconcile_with_session(session)
        current = await session.get(MonitoringService, service_id)
        assert current.status is False
        assert current.desired_state == "running"
        assert current.operational_stage == "failed"
        assert current.operational_status == FAILED_TASK
        assert current.operational_updated_at == heartbeat

    await set_runtime(sessions, workload, RUNTIME)
    await wait_for_workload_state(workloads, workload, "running")
    async with sessions() as session:
        await reconciler._reconcile_with_session(session)
        current = await session.get(MonitoringService, service_id)
        assert current.status and current.desired_state == "running"
        assert current.operational_stage == "starting"
        assert current.operational_status["is_stale"] is True
        assert current.operational_updated_at is None


@pytest.mark.asyncio
async def test_stale_running_observation_cannot_revive_newer_stop_generation(
    lifecycle_database, pool_workloads, monkeypatch
):
    sessions = lifecycle_database
    workloads, _ = pool_workloads
    service_id, workload = await running_monitor(sessions, workloads)
    heartbeat = await record_operational_status(
        sessions, service_id, "failed", FAILED_TASK, status=False
    )
    reconciler = RadarStatusReconciliationService(workloads=workloads)
    async with paused_reconciliation(reconciler, sessions, monkeypatch) as observations:
        assert observations == {workload.id: "running"}
        stop_requested_at = datetime.now(UTC)
        async with asyncio.timeout(2), sessions.begin() as writer:
            await writer.execute(
                update(MonitoringService)
                .where(MonitoringService.id == service_id)
                .values(
                    desired_state="stopped",
                    lifecycle_version=MonitoringService.lifecycle_version + 1,
                    stop_requested_at=stop_requested_at,
                )
            )
    async with sessions() as session:
        current = await session.get(MonitoringService, service_id)
        assert current.desired_state == "stopped"
        assert current.lifecycle_version == 2
        assert current.stop_requested_at == stop_requested_at
        assert current.status is False
        assert current.operational_stage == "failed"
        assert current.operational_status == FAILED_TASK
        assert current.operational_updated_at == heartbeat


@pytest.mark.asyncio
async def test_legacy_monitor_keeps_sensor_claim_through_a_failed_worker_and_restart(
    lifecycle_database, pool_workloads
):
    sessions = lifecycle_database
    workloads, pool = pool_workloads
    service_id, workload = await running_monitor(sessions, workloads)
    async with sessions.begin() as session:
        await session.execute(
            update(MonitoringService)
            .where(MonitoringService.id == service_id)
            .values(
                config_fingerprint=None,
                status=False,
                operational_updated_at=datetime.now(UTC) - timedelta(days=7),
            )
        )
    reconciler = RadarStatusReconciliationService(
        terminal_service_retention_hours=0, workloads=workloads
    )
    await kill_child(pool, workload)
    await wait_for_workload_state(workloads, workload, "failed")
    async with sessions() as session:
        await reconciler._reconcile_with_session(session)
        current = await session.get(MonitoringService, service_id)
        assert current.config_fingerprint is None
        assert current.status and current.desired_state == "running"
        assert current.operational_stage == "failed"
    async with sessions() as session:
        with pytest.raises(ValueError, match="overlaps active service"):
            await radar_module.RadarOrchestrationService(
                session
            )._assert_topics_available(
                mqtt_topics=["telemetry/entity/value"], container_name="replacement"
            )
    # An operator hands the failed workload back to the pool.
    async with sessions.begin() as session:
        await session.execute(
            update(RadarWorkload)
            .where(RadarWorkload.id == workload.id)
            .values(state="pending", crashes=[])
        )
    await wait_for_workload_state(workloads, workload, "running")
    async with sessions() as session:
        await reconciler._reconcile_with_session(session)
        current = await session.get(MonitoringService, service_id)
        assert current.status and current.desired_state == "running"


@pytest.mark.asyncio
async def test_delete_holds_claim_until_the_child_stops_without_database_lock(
    lifecycle_database, pool_workloads
):
    sessions = lifecycle_database
    workloads, pool = pool_workloads
    service_id, workload = await running_monitor(sessions, workloads, code=SLOW_STOP)
    child = pool.children[workload.id].process
    async with sessions() as session:
        service = radar_module.RadarOrchestrationService(session)
        started = time.monotonic()
        deleting = asyncio.create_task(service.delete_radar_service(service_id))
        async with asyncio.timeout(10):
            while True:
                async with sessions() as observer:
                    row = await observer.get(RadarWorkload, workload.id)
                    if row is not None and row.desired == "stop":
                        break
                await asyncio.sleep(0.01)
        async with asyncio.timeout(1), sessions.begin() as concurrent:
            await lock_collection_configuration(concurrent)
            row = await concurrent.get(MonitoringService, service_id)
            assert row is not None and row.status and row.desired_state == "deleted"
            row.operational_updated_at = datetime.now(UTC)
        assert await deleting
        assert time.monotonic() - started >= 1.5
        # The claim went only after the child had ended.
        assert child.returncode == 0
    async with sessions() as session:
        assert await session.get(MonitoringService, service_id) is None
        assert await session.get(RadarWorkload, workload.id) is None


@pytest.mark.asyncio
async def test_a_stop_keeps_the_claim_while_no_replica_confirms_it(
    lifecycle_database, pool_workloads, monkeypatch
):
    """A replica that holds the lease but never answers keeps the claim."""
    monkeypatch.setenv("TACTIC_RADAR_STOP_TIMEOUT_SECONDS", "1")
    sessions = lifecycle_database
    workloads, pool = pool_workloads
    service_id, workload = await running_monitor(sessions, workloads)
    # The replica keeps its lease but stops looking at its rows.
    pool.renew = pool.reap = pool.claim = _no_op
    async with sessions.begin() as session:
        await session.execute(
            update(RadarWorkload)
            .where(RadarWorkload.id == workload.id)
            .values(lease_expires_at=datetime.now(UTC) + timedelta(minutes=5))
        )
    async with sessions() as session:
        service = radar_module.RadarOrchestrationService(session)
        assert await service.delete_radar_service(service_id) is False
    async with sessions() as session:
        retained = await session.get(MonitoringService, service_id)
        assert retained is not None and retained.status
        assert retained.desired_state == "deleted"
        assert await session.get(RadarWorkload, workload.id) is not None


async def _no_op():
    return None


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrent_change", ["catalogue", "monitor"])
async def test_collection_edit_revalidates_revision_after_unlocked_real_stop(
    lifecycle_database,
    pool_workloads,
    monkeypatch,
    concurrent_change,
):
    from tests.support.system_document import document

    sessions = lifecycle_database
    workloads, _ = pool_workloads
    monkeypatch.setattr(
        collection_monitors, "get_async_session_local", lambda: sessions
    )
    monkeypatch.setattr(
        system_collection,
        "get_system_live_settings",
        lambda: SystemLiveSettings(SYSTEM_LIVE_ALLOWED_HOSTS=["localhost"]),
    )
    async with sessions() as session:
        initial = document()
        initial.streams.append(
            initial.streams[0].model_copy(
                update={"id": "humidity", "payload_pointer": "/humidity"}
            )
        )
        saved = await SystemService(session).save(
            SystemChange(expected_revision=0, document=initial), actor="review"
        )
        saved = await SystemService(session).apply_collection(
            SystemCollectionChange(
                expected_revision=saved.revision,
                expected_collection_revision=saved.runtime.collection_revision,
                stream_ids=["temperature-1", "humidity"],
                policy=CollectionPolicy(mode="original"),
            ),
            actor="review",
        )
        await session.commit()
    service_id, _ = await pending_monitor(sessions, workloads)
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
    original_stop = RadarWorkloadManager.request_stop

    async def delayed_stop(self, workload_id):
        await original_stop(self, workload_id)
        entered.set()
        await release.wait()

    monkeypatch.setattr(RadarWorkloadManager, "request_stop", delayed_stop)
    edit = saved.document.model_copy(deep=True)
    for stream in edit.streams:
        stream.payload_pointer = "/changed"

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
            if concurrent_change == "catalogue":
                renamed = latest.document.model_copy(deep=True)
                renamed.label = "Concurrent save"
                await SystemService(session).save(
                    SystemChange(expected_revision=latest.revision, document=renamed),
                    actor="second",
                )
            else:
                await lock_collection_configuration(session)
                topic = latest.runtime.bindings["humidity"]["accepted_topic"]
                await radar_module.RadarOrchestrationService(
                    session
                )._assert_topics_available(
                    mqtt_topics=[topic], container_name="new-pending"
                )
                session.add(
                    MonitoringService(
                        id="new-pending",
                        container_name="new-pending",
                        mqtt_topic=[topic],
                        status=True,
                        desired_state="running",
                    )
                )
            await session.commit()
    finally:
        release.set()
    expected = (
        "changed while monitors stopped"
        if concurrent_change == "catalogue"
        else "new monitor started"
    )
    with pytest.raises(ConflictError, match=expected):
        await task
    async with sessions() as session:
        latest = await SystemService(session).read()
        monitor = await session.get(MonitoringService, service_id)
        if concurrent_change == "catalogue":
            assert latest.document.label == "Concurrent save"
        else:
            assert (await session.get(MonitoringService, "new-pending")).status
        assert latest.document.streams[0].payload_pointer != "/changed"
        assert not monitor.status and monitor.desired_state == "stopped"
