"""Real pool preflight, handoff and cancellation using isolated PostgreSQL/MQTT.

The pool replica runs in this process and its children run the real RADAR
modules, so a preflight builds the pipeline and a monitor admits, subscribes
and heartbeats exactly as it does deployed.
"""

import asyncio
import time
from uuid import uuid4

import pytest
import pytest_asyncio
from off_key_core.db.models import MonitoringService, PipelineActivation
from off_key_core.db.workloads import RadarWorkload
from off_key_core.models.pipelines import pipeline_catalog
from off_key_core.schemas.pipelines import (
    PipelineActivationRequest,
    PipelineCreate,
    PipelineDraftSave,
    PipelinePublish,
)
from off_key_core.schemas.radar import RadarStartConfig
from off_key_tactic_middleware.config.config import clear_tactic_settings_caches
from off_key_tactic_middleware.services.orchestration import radar_workloads
from off_key_tactic_middleware.services.orchestration.radar import (
    RadarOrchestrationService,
)
from off_key_tactic_middleware.services.orchestration.radar_workloads import (
    RadarWorkloadManager,
)
from off_key_tactic_middleware.services.pipelines.activation import PipelineActivations
from off_key_tactic_middleware.services.pipelines.library import PipelineLibrary
from off_key_tactic_middleware.services.pipelines.preflight import PipelinePreflight
from off_key_tactic_middleware.services.pipelines.preflight_cleanup import (
    PreflightOrphans,
)

from tests.support.mqtt import mqtt_broker
from tests.support.radar_pool import RUNTIME, running_pool

pytestmark = pytest.mark.radar_integration

# A runtime no replica runs: its jobs wait for room that never comes.
NOWHERE = "registry/radar:nowhere"


@pytest_asyncio.fixture
async def activation_runtime(pipeline_database, monkeypatch):
    url = pipeline_database.kw["bind"].url
    async with mqtt_broker() as (_, port):
        environment = {
            "ENVIRONMENT": "development",
            # The pool's children inherit these, as from a deployed replica.
            "POSTGRES_USER": url.username,
            "POSTGRES_PASSWORD": url.password or "",
            "POSTGRES_HOST": url.host,
            "POSTGRES_PORT": str(url.port or 5432),
            "POSTGRES_DB": url.database,
            "TACTIC_RADAR_IMAGE": RUNTIME,
            "TACTIC_RADAR_DEFAULT_MQTT_BROKER_HOST": "127.0.0.1",
            "TACTIC_RADAR_DEFAULT_MQTT_BROKER_PORT": str(port),
            "TACTIC_RADAR_DEFAULT_MQTT_USE_TLS": "false",
            "TACTIC_RADAR_DEFAULT_MQTT_USE_AUTH": "false",
            "TACTIC_RADAR_DEFAULT_HEALTH_CHECK_INTERVAL": "1",
            "TACTIC_RADAR_STARTUP_GRACE_SECONDS": "0.1",
        }
        for name, value in environment.items():
            monkeypatch.setenv(name, value)
        monkeypatch.setattr(
            radar_workloads, "get_async_session_local", lambda: pipeline_database
        )
        clear_tactic_settings_caches()
        workloads = RadarWorkloadManager()
        activations = []
        engine = pipeline_database.kw["bind"]
        try:
            async with running_pool(
                engine, code=None, poll_seconds=0.2, lease_seconds=10.0
            ):
                yield pipeline_database, workloads, activations
                for activation in activations:
                    await workloads.remove_intent(activation.service_id, None)
                    await PipelinePreflight(workloads).remove_for(activation.id)
        finally:
            clear_tactic_settings_caches()


async def drive_activation(sessions, workloads, identifier, *, until="succeeded"):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        async with sessions() as session:
            controller = PipelineActivations(session, workloads=workloads)
            status = await controller.get(identifier)
            if status.phase == until:
                return status
            assert status.phase not in {"failed", "cancelled"}, status.error
            # A fresh session/controller each step proves persisted recovery.
            await controller.advance(identifier)
        await asyncio.sleep(0.25)
    async with sessions() as session:
        status = await PipelineActivations(session).get(identifier)
    raise AssertionError(f"Activation did not reach {until}: {status.model_dump()}")


async def submit_activation(
    sessions, workloads, owned, revision_id, *, predecessor=None, key=None
):
    async with sessions() as session:
        result = await PipelineActivations(session, workloads=workloads).submit(
            PipelineActivationRequest(
                revision_id=revision_id,
                bindings={"value": "current"},
                display_name="Isolated pool monitor",
                idempotency_key=key or str(uuid4()),
                replace_service_id=predecessor,
            )
        )
    owned.append(result)
    return result


@pytest.mark.asyncio
@pytest.mark.timeout(120)
async def test_preflight_cancellation_preserves_a_foreign_name_collision(
    activation_runtime,
):
    sessions, workloads, owned = activation_runtime
    async with sessions() as session:
        library = PipelineLibrary(session)
        design = await library.create(
            PipelineCreate(
                name="Preflight ownership",
                definition=pipeline_catalog().templates[1].definition,
            )
        )
        revision = await library.publish(design.id, PipelinePublish(expected_version=1))
    activation = await submit_activation(sessions, workloads, owned, revision.id)
    # This test owns the synthetic foreign job and removes it explicitly.
    # Application cancellation must not remove it just because the name matches.
    foreign = await workloads.submit(
        name=f"radar-preflight-{activation.id}",
        kind="preflight",
        module="foreign.job",
        runtime=NOWHERE,
        environment={},
        labels={"managed_by": "foreign-fixture"},
        restart=False,
    )
    try:
        async with sessions() as session:
            controller = PipelineActivations(session, workloads=workloads)
            await controller.cancel(activation.id)
            await controller.advance(activation.id)
            progress = await controller.get(activation.id)
            assert progress.phase == "cancelling"
            assert "different owner" in progress.error
        retained = await workloads.get(foreign.id)
        assert retained is not None and retained.labels == foreign.labels
        async with sessions() as session:
            assert (await session.get(RadarWorkload, foreign.id)).desired == "run"
    finally:
        await workloads.remove(foreign.id)
    await drive_activation(sessions, workloads, activation.id, until="failed")


@pytest.mark.asyncio
@pytest.mark.timeout(600)
async def test_real_preflight_handoff_recovery_and_newer_stop(
    activation_runtime, monkeypatch
):
    sessions, workloads, owned = activation_runtime
    async with sessions() as session:
        library = PipelineLibrary(session)
        design = await library.create(
            PipelineCreate(
                name="Pool integration",
                definition=pipeline_catalog().templates[1].definition,
            )
        )
        first_revision = await library.publish(
            design.id, PipelinePublish(expected_version=1)
        )
    first = await submit_activation(sessions, workloads, owned, first_revision.id)
    await drive_activation(sessions, workloads, first.id)
    predecessor = await workloads.find(first.service_id)
    assert predecessor is not None and predecessor.state == "running"
    async with sessions() as session:
        row = await session.get(PipelineActivation, first.id)
        assert row.preflight["ok"]
        assert row.image_digest == RUNTIME
        assert (
            await session.get(MonitoringService, first.service_id)
        ).operational_updated_at is not None
        library = PipelineLibrary(session)
        current = await library.get(design.id)
        draft = current.draft.model_copy(deep=True)
        draft.settings.training_window_size += 1
        saved = await library.save_draft(
            design.id,
            PipelineDraftSave(expected_version=current.version, definition=draft),
        )
        second_revision = await library.publish(
            design.id, PipelinePublish(expected_version=saved.version)
        )
    second = await submit_activation(
        sessions, workloads, owned, second_revision.id, predecessor=first.service_id
    )
    await drive_activation(sessions, workloads, second.id, until="starting")
    # No successor has started while the predecessor's child could still run:
    # its row goes only once the pool confirmed the child ended.
    assert await workloads.get(predecessor.id) is None
    assert await workloads.find(first.service_id) is None
    async with sessions() as session:
        row = await session.get(PipelineActivation, second.id)
        with pytest.raises(ValueError, match="pending pipeline activation"):
            await RadarOrchestrationService(
                session, workloads=workloads
            )._assert_topics_available(
                mqtt_topics=row.launch_config["mqtt_topics"],
                container_name="competing-legacy",
            )
    await drive_activation(sessions, workloads, second.id)
    async with sessions() as session:
        service = await PipelineLibrary(session).service(second.service_id)
        assert [run.service_id for run in service.history] == [
            second.service_id,
            first.service_id,
        ]
        assert service.history[1].ended_at is not None
        assert (
            await PipelineLibrary(session).service(first.service_id)
        ).run.id == first.run_id
    # Explicit cancellation before retirement leaves the established worker active.
    third = await submit_activation(
        sessions, workloads, owned, first_revision.id, predecessor=second.service_id
    )
    async with sessions() as session:
        await PipelineActivations(session, workloads=workloads).cancel(third.id)
    await drive_activation(sessions, workloads, third.id, until="cancelled")
    assert await workloads.find(second.service_id) is not None
    # A lost create may arrive after cancellation found nothing. The sweep must
    # reap that delayed job without touching B.
    async with sessions() as session:
        cancelled = await session.get(PipelineActivation, third.id)
        configuration = RadarStartConfig.model_validate(cancelled.launch_config)
        preflight = PipelinePreflight(workloads)
        image = await preflight.resolve_image()
        await preflight._ensure(third.id, configuration.pipeline, image)
        await PreflightOrphans(session, workloads).sweep()
    assert await workloads.find_named(f"radar-preflight-{third.id}") is None
    assert await workloads.find(second.service_id) is not None
    # A job no replica can run must fail boundedly after confirmed cleanup.
    monkeypatch.setenv("TACTIC_RADAR_IMAGE", NOWHERE)
    monkeypatch.setenv("TACTIC_PIPELINE_PREFLIGHT_TIMEOUT_SECONDS", "5")
    clear_tactic_settings_caches()
    rejected = await submit_activation(
        sessions, workloads, owned, first_revision.id, predecessor=second.service_id
    )
    failure = await drive_activation(sessions, workloads, rejected.id, until="failed")
    assert "timed out: no RADAR pool replica has room" in failure.error
    assert await workloads.find(second.service_id) is not None
    assert await workloads.find_named(f"radar-preflight-{rejected.id}") is None
    monkeypatch.setenv("TACTIC_RADAR_IMAGE", RUNTIME)
    monkeypatch.setenv("TACTIC_PIPELINE_PREFLIGHT_TIMEOUT_SECONDS", "90")
    clear_tactic_settings_caches()
    # A newer stop during preflight supersedes replacement and cannot be undone.
    fourth = await submit_activation(
        sessions, workloads, owned, first_revision.id, predecessor=second.service_id
    )
    await drive_activation(sessions, workloads, fourth.id, until="validated")
    async with sessions() as session:
        assert await RadarOrchestrationService(
            session, workloads=workloads
        ).delete_radar_service(second.service_id)
    await drive_activation(sessions, workloads, fourth.id, until="cancelled")
    assert await workloads.find(fourth.service_id) is None
