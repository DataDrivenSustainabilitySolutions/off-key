"""Real Swarm preflight, handoff and cancellation using isolated PostgreSQL/MQTT."""

import asyncio
import io
import tarfile
import time
from contextlib import suppress
from uuid import uuid4

import docker
import pytest
import pytest_asyncio
from off_key_core.db.models import MonitoringService, PipelineActivation
from off_key_core.models.pipelines import pipeline_catalog
from off_key_core.schemas.pipelines import (
    PipelineActivationRequest,
    PipelineCreate,
    PipelineDraftSave,
    PipelinePublish,
)
from off_key_core.schemas.radar import RadarStartConfig
from off_key_tactic_middleware.config.config import (
    DockerConfig,
    clear_tactic_settings_caches,
)
from off_key_tactic_middleware.facades.docker import AsyncDocker
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
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

from . import test_monitoring_pipelines_integration as pipeline_integration

pytestmark = pytest.mark.radar_integration

pipeline_database = pipeline_integration.pipeline_database


class SwarmFixtureSettings(BaseSettings):
    TEST_RADAR_DOCKER: bool = False
    TEST_PIPELINE_DATABASE_CONTAINER: str | None = None
    TEST_PIPELINE_RUNTIME_IMAGE: str = Field(
        default="offkey-pipelines-control:dev",
        validation_alias=AliasChoices(
            "TEST_PIPELINE_RUNTIME_IMAGE", "TEST_RADAR_SWARM_IMAGE"
        ),
    )
    TEST_PIPELINE_MQTT_IMAGE: str = "eclipse-mosquitto:2.0"


def broker_configuration() -> bytes:
    output = io.BytesIO()
    contents = b"listener 1883 0.0.0.0\nallow_anonymous true\npersistence false\n"
    with tarfile.open(fileobj=output, mode="w") as archive:
        member = tarfile.TarInfo("offkey-pipeline-test.conf")
        member.size = len(contents)
        member.mode = 0o444
        archive.addfile(member, io.BytesIO(contents))
    return output.getvalue()


@pytest_asyncio.fixture
async def activation_runtime(pipeline_database, monkeypatch):
    options = SwarmFixtureSettings()
    if not options.TEST_RADAR_DOCKER:
        pytest.skip("Set TEST_RADAR_DOCKER=1 for the isolated Swarm activation journey")
    assert options.TEST_PIPELINE_DATABASE_CONTAINER, (
        "Set TEST_PIPELINE_DATABASE_CONTAINER to the owned disposable schema fixture"
    )
    client = docker.from_env()
    assert client.info().get("Swarm", {}).get("ControlAvailable")
    identifier = uuid4().hex[:12]
    network = client.networks.create(
        f"offkey-pipeline-control-{identifier}",
        driver="overlay",
        scope="swarm",
        attachable=True,
    )
    database = client.containers.get(options.TEST_PIPELINE_DATABASE_CONTAINER)
    workloads = RadarWorkloadManager(AsyncDocker(DockerConfig(), client=client))
    activations = []
    broker = None
    connected = False
    try:
        network.connect(database, aliases=["pipeline-fixture-postgres"])
        connected = True
        broker = client.containers.create(
            options.TEST_PIPELINE_MQTT_IMAGE,
            name=f"offkey-pipeline-mqtt-{identifier}",
            command=["mosquitto", "-c", "/tmp/offkey-pipeline-test.conf"],
            network=network.name,
        )
        broker.put_archive("/tmp", broker_configuration())
        broker.start()
        url = pipeline_database.kw["bind"].url
        environment = {
            "ENVIRONMENT": "development",
            "POSTGRES_USER": url.username,
            "POSTGRES_PASSWORD": url.password,
            "POSTGRES_HOST": "pipeline-fixture-postgres",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": url.database,
            "TACTIC_RADAR_IMAGE": options.TEST_PIPELINE_RUNTIME_IMAGE,
            "TACTIC_DOCKER_DEFAULT_NETWORK": network.name,
            "TACTIC_DOCKER_ADDITIONAL_NETWORKS": "",
            "TACTIC_DOCKER_DEFAULT_CONSTRAINTS": "",
            "TACTIC_RADAR_DEFAULT_MQTT_BROKER_HOST": broker.name,
            "TACTIC_RADAR_DEFAULT_MQTT_BROKER_PORT": "1883",
            "TACTIC_RADAR_DEFAULT_MQTT_USE_TLS": "false",
            "TACTIC_RADAR_DEFAULT_MQTT_USE_AUTH": "false",
            "TACTIC_RADAR_DEFAULT_HEALTH_CHECK_INTERVAL": "1",
            "TACTIC_RADAR_STARTUP_GRACE_SECONDS": "0.1",
        }
        for name, value in environment.items():
            monkeypatch.setenv(name, value)
        clear_tactic_settings_caches()
        yield pipeline_database, workloads, activations
    finally:
        for activation in activations:
            await workloads.remove_intent(activation.service_id, None)
            with suppress(docker.errors.NotFound):
                job = client.services.get(f"radar-preflight-{activation.id}")
                await workloads.remove(job.id)
        if broker is not None:
            broker.remove(force=True)
        if connected:
            network.disconnect(database, force=True)
        for attempt in range(30):
            try:
                network.remove()
                break
            except docker.errors.APIError:
                if attempt == 29:
                    raise
                await asyncio.sleep(0.5)
        client.close()
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
                display_name="Isolated Swarm monitor",
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
    image = await PipelinePreflight(workloads).resolve_image()
    # This fixture owns the synthetic foreign job and removes it explicitly.
    # Application cancellation must not remove it just because the name matches.
    labels = {
        "managed_by": "foreign-fixture",
        "off-key.integration-owner": f"foreign-preflight-{activation.id}",
    }
    foreign = await workloads.async_docker.run(
        workloads.async_docker.client.services.create,
        image=image,
        name=f"radar-preflight-{activation.id}",
        # Python is PID 1 here, so explicitly handle SIGTERM rather than making
        # cleanup depend on Swarm's forced-kill deadline and task-start timing.
        command=[
            "/app/bin/python",
            "-c",
            "import signal, sys, time; "
            "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); "
            "print('foreign-preflight-ready', flush=True); time.sleep(120)",
        ],
        restart_policy=docker.types.RestartPolicy(condition="none"),
        labels=labels,
        container_labels=labels,
    )
    try:
        async with asyncio.timeout(30):
            while True:
                tasks = await workloads.async_docker.run(foreign.tasks)
                running = [
                    task for task in tasks if task["Status"]["State"] == "running"
                ]
                if running and b"foreign-preflight-ready" in (
                    await workloads.async_docker.run(
                        lambda: b"".join(foreign.logs(stdout=True, stderr=True))
                    )
                ):
                    foreign_task_id = running[0]["ID"]
                    break
                await asyncio.sleep(0.05)
        async with sessions() as session:
            controller = PipelineActivations(session, workloads=workloads)
            await controller.cancel(activation.id)
            await controller.advance(activation.id)
            progress = await controller.get(activation.id)
            assert progress.phase == "cancelling"
            assert "different owner" in progress.error
        retained = await workloads.async_docker.run(
            workloads.async_docker.client.services.get, foreign.id
        )
        assert retained.attrs["Spec"]["Mode"]["Replicated"]["Replicas"] == 1
        assert any(
            task["ID"] == foreign_task_id and task["Status"]["State"] == "running"
            for task in await workloads.async_docker.run(foreign.tasks)
        )
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
                name="Swarm integration",
                definition=pipeline_catalog().templates[1].definition,
            )
        )
        first_revision = await library.publish(
            design.id, PipelinePublish(expected_version=1)
        )
    first = await submit_activation(sessions, workloads, owned, first_revision.id)
    await drive_activation(sessions, workloads, first.id)
    predecessor_workload_id = workloads.async_docker.client.services.get(
        f"radar-{first.service_id}"
    ).id
    async with sessions() as session:
        row = await session.get(PipelineActivation, first.id)
        assert row.preflight["ok"]
        assert row.image_digest.startswith("sha256:") or "@sha256:" in row.image_digest
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
    # No successor has started while the predecessor's tasks can still execute.
    tasks = await workloads._remaining_service_tasks(predecessor_workload_id)
    assert all(
        task.get("Status", {}).get("State")
        in {"shutdown", "complete", "failed", "rejected", "remove"}
        for task in tasks
    )
    with pytest.raises(docker.errors.NotFound):
        workloads.async_docker.client.services.get(f"radar-{first.service_id}")
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
    assert workloads.async_docker.client.services.get(f"radar-{second.service_id}")
    # A lost create may arrive after cancellation's NotFound response. The
    # controller-scoped sweep must reap that real delayed job without touching B.
    async with sessions() as session:
        cancelled = await session.get(PipelineActivation, third.id)
        configuration = RadarStartConfig.model_validate(cancelled.launch_config)
        preflight = PipelinePreflight(workloads)
        image = await preflight.resolve_image()
        await preflight._create(third.id, configuration.pipeline, image, True)
        await PreflightOrphans(session, workloads).sweep()
    with pytest.raises(docker.errors.NotFound):
        workloads.async_docker.client.services.get(f"radar-preflight-{third.id}")
    assert workloads.async_docker.client.services.get(f"radar-{second.service_id}")
    # An unschedulable real job must fail boundedly after confirmed cleanup.
    monkeypatch.setenv(
        "TACTIC_DOCKER_DEFAULT_CONSTRAINTS",
        f"node.labels.offkey_fixture_{uuid4().hex} == true",
    )
    monkeypatch.setenv("TACTIC_PIPELINE_PREFLIGHT_TIMEOUT_SECONDS", "5")
    clear_tactic_settings_caches()
    rejected = await submit_activation(
        sessions, workloads, owned, first_revision.id, predecessor=second.service_id
    )
    failure = await drive_activation(sessions, workloads, rejected.id, until="failed")
    assert "timed out" in failure.error
    assert workloads.async_docker.client.services.get(f"radar-{second.service_id}")
    with pytest.raises(docker.errors.NotFound):
        workloads.async_docker.client.services.get(f"radar-preflight-{rejected.id}")
    monkeypatch.setenv("TACTIC_DOCKER_DEFAULT_CONSTRAINTS", "")
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
    with pytest.raises(docker.errors.NotFound):
        workloads.async_docker.client.services.get(f"radar-{fourth.service_id}")
