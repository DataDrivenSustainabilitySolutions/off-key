"""Real PostgreSQL coverage for designs, durable claims and release arbitration."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from off_key_core.db.collection_runtime import read_collection_runtime
from off_key_core.db.models import (
    DeploymentMaintenance,
    MonitoringPipeline,
    MonitoringService,
    PipelineActivation,
    PipelineRevision,
    PipelineRun,
    RadarRuntimeCheckpoint,
)
from off_key_core.models.pipelines import pipeline_catalog
from off_key_core.schemas.collection_policy import CollectionPolicy
from off_key_core.schemas.pipelines import (
    PipelineActivationRequest,
    PipelineApplyRequest,
    PipelineCreate,
    PipelineDraftSave,
    PipelineExecutionConfig,
    PipelineLayout,
    PipelinePublish,
)
from off_key_mqtt_radar.admission import (
    RadarAdmissionSettings,
    require_monitor_admission,
)
from off_key_mqtt_radar.config.config import MQTTRadarConfig
from off_key_mqtt_radar.database import DatabaseWriter
from off_key_tactic_middleware.config.config import get_tactic_settings
from off_key_tactic_middleware.deployment import reserve
from off_key_tactic_middleware.domain import ConflictError, ValidationError
from off_key_tactic_middleware.services.catalogue.system_collection import (
    SystemCollectionService,
)
from off_key_tactic_middleware.services.orchestration.radar import (
    RadarOrchestrationService,
)
from off_key_tactic_middleware.services.pipelines.activation import PipelineActivations
from off_key_tactic_middleware.services.pipelines.library import PipelineLibrary
from off_key_tactic_middleware.services.pipelines.preflight import (
    PipelinePreflight,
    PreflightRejected,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.support.pipeline_database import published_design

pytestmark = pytest.mark.radar_integration


@pytest.mark.asyncio
async def test_direct_apply_is_atomic_idempotent_and_separate_from_templates(
    pipeline_database,
):
    async with pipeline_database() as session:
        library = PipelineLibrary(session)
        template = await library.create(
            PipelineCreate(
                name="Reusable",
                definition=pipeline_catalog().templates[0].definition,
            )
        )
        request = PipelineApplyRequest(
            definition=template.draft,
            layout=PipelineLayout(nodes={"input": {"x": 32, "y": 48}}),
            bindings={"value": "current"},
            display_name="  Current monitor  ",
            idempotency_key="direct-apply",
        )
        activation = await PipelineActivations(session).apply(request)
        assert (await PipelineActivations(session).apply(request)).id == activation.id
        assert [item.id for item in (await library.list()).items] == [template.id]
        assert await library.get(template.id) == template
        run = await session.get(PipelineRun, activation.run_id)
        assert run.layout["nodes"]["input"]["x"] == 32
        assert run.launch_config["display_name"] == "Current monitor"
        execution = PipelineExecutionConfig.model_validate(run.execution)
        assert execution.definition == template.draft
        assert execution.bindings[0].reading_id == "current"
        with pytest.raises(ConflictError, match="Idempotency"):
            await PipelineActivations(session).apply(
                request.model_copy(update={"display_name": "Other"})
            )
        await session.rollback()
        # A failed new apply must not leave behind a configuration or source claim.
        identifiers = set(await session.scalars(select(MonitoringPipeline.id)))
        with pytest.raises(ValidationError, match="every named input"):
            await PipelineActivations(session).apply(
                request.model_copy(
                    update={
                        "idempotency_key": "invalid-apply",
                        "bindings": {"missing": "temperature"},
                    }
                )
            )
        await session.rollback()
        assert set(await session.scalars(select(MonitoringPipeline.id))) == identifiers


@pytest.mark.asyncio
async def test_library_drafts_concurrency_and_immutable_revisions(pipeline_database):
    async with pipeline_database() as session:
        library = PipelineLibrary(session)
        design, revision = await published_design(session)
        current = await library.get(design.id)
        assert current.version == 2
        changed = current.draft.model_copy(deep=True)
        changed.nodes = []
        saved = await library.save_draft(
            design.id, PipelineDraftSave(expected_version=2, definition=changed)
        )
        assert saved.version == 3
        assert not (await library.validate(design.id, changed)).valid
        with pytest.raises(ConflictError):
            await library.save_draft(
                design.id,
                PipelineDraftSave(expected_version=2, definition=current.draft),
            )
        await session.rollback()
        with pytest.raises(ValidationError):
            await library.publish(design.id, PipelinePublish(expected_version=3))
        await session.rollback()
        assert (
            await library.revision(design.id, revision.id)
        ).definition == revision.definition


@pytest.mark.asyncio
async def test_activation_binding_and_persisted_union_claims(pipeline_database):
    async with pipeline_database() as session:
        _, revision = await published_design(session)
        request = PipelineActivationRequest(
            revision_id=revision.id,
            bindings={"value": "current"},
            display_name="Current monitor",
            idempotency_key="binding-claim",
        )
        activations = PipelineActivations(session)
        activation = await activations.submit(request)
        assert activation.phase == "requested"
        assert (await activations.submit(request)).id == activation.id
        altered = request.model_copy(update={"display_name": "Different"})
        with pytest.raises(ConflictError, match="Idempotency"):
            await activations.submit(altered)
        await session.rollback()
        row = await session.get(PipelineActivation, activation.id)
        assert row.launch_config["launch_version"] == 2
        run = await session.get(PipelineRun, activation.run_id)
        assert run.binding_metadata["readings"][0]["label"] == "Current"
        assert run.binding_metadata["readings"][0]["source_label"] == "Fixture"
        assert run.binding_metadata["collection_revision"] == 1
        snapshot = await read_collection_runtime(session)
        topic = next(
            item.accepted_topic
            for item in snapshot.catalog.streams()
            if item.definition.id == "current"
        )
        assert row.claim_topics == [topic]
        with pytest.raises(ValueError, match="pending pipeline activation"):
            await RadarOrchestrationService(session)._assert_topics_available(
                mqtt_topics=[topic], container_name="legacy"
            )
        await session.rollback()
        with pytest.raises(ValueError, match="pending pipeline activations"):
            await reserve(session, "a" * 40)
        await session.rollback()
        await activations.cancel(activation.id)
        # Cancellation requests do not release uncertain ownership prematurely.
        with pytest.raises(ValueError, match="pending pipeline activations"):
            await reserve(session, "a" * 40)


@pytest.mark.asyncio
async def test_stop_predetermined_service_cancels_its_pending_activation(
    pipeline_database,
):
    async with pipeline_database() as session:
        _, revision = await published_design(session)
        activation = await PipelineActivations(session).submit(
            PipelineActivationRequest(
                revision_id=revision.id,
                bindings={"value": "current"},
                display_name="Pending",
                idempotency_key="stop-pending",
            )
        )
        assert await RadarOrchestrationService(session).delete_radar_service(
            activation.service_id
        )
        row = await session.get(
            PipelineActivation, activation.id, populate_existing=True
        )
        assert row.cancel_requested
        assert row.phase == "requested"


@pytest.mark.asyncio
async def test_run_history_and_layout_survive_service_and_checkpoint_removal(
    pipeline_database,
):
    async with pipeline_database() as session:
        _, revision = await published_design(session)
        activation = await PipelineActivations(session).submit(
            PipelineActivationRequest(
                revision_id=revision.id,
                bindings={"value": "current"},
                display_name="History",
                idempotency_key="retained-history",
            )
        )
        run = await session.get(PipelineRun, activation.run_id)
        session.add(
            MonitoringService(
                id=run.service_id,
                container_name=run.launch_config["container_name"],
                mqtt_topic=run.launch_config["mqtt_topics"],
                launch_config=run.launch_config,
                status=True,
            )
        )
        await session.flush()
        session.add(
            RadarRuntimeCheckpoint(
                service_id=run.service_id,
                format_version=1,
                configuration_fingerprint="configuration",
                runtime_fingerprint="runtime",
                processed_count=0,
                saved_at=datetime.now(UTC),
                payload=b"fixture",
                signature="fixture",
            )
        )
        await session.commit()
        library = PipelineLibrary(session)
        initial = await library.service(run.service_id)
        saved = await library.layout(
            run.service_id,
            PipelineLayout(
                nodes={"input": {"x": 100, "y": 200}}, version=initial.layout.version
            ),
        )
        assert saved.version == initial.layout.version + 1
        with pytest.raises(ConflictError, match="arrangement changed"):
            await library.layout(run.service_id, initial.layout)
        await session.rollback()
        await session.refresh(run)
        await session.execute(
            delete(MonitoringService).where(MonitoringService.id == run.service_id)
        )
        await session.commit()
        assert (
            await session.scalar(
                select(RadarRuntimeCheckpoint).where(
                    RadarRuntimeCheckpoint.service_id == run.service_id
                )
            )
            is None
        )
        retained = await library.service(run.service_id)
        assert retained.run.id == run.id
        assert retained.history[0].revision_id == revision.id
        assert retained.layout.nodes["input"].x == 100


@pytest.mark.asyncio
async def test_release_reservation_before_pipeline_tables_exist(disposable_database):
    with disposable_database.begin() as connection:
        MonitoringService.__table__.create(connection)
        DeploymentMaintenance.__table__.create(connection)
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            assert (await reserve(session, "a" * 40))["phase"] == "quiescing"
            assert (await reserve(session, "a" * 40))["phase"] == "quiescing"
            with pytest.raises(ValueError, match="different release"):
                await reserve(session, "b" * 40)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("stale_result", ["success", "rejected", "error"])
async def test_expired_activation_controller_cannot_overwrite_new_owner(
    pipeline_database, monkeypatch, stale_result
):
    """Only the remote I/O boundary is held; both controllers use real DB locks."""
    entered, released = asyncio.Event(), asyncio.Event()
    workloads = SimpleNamespace(async_docker=None)
    calls = 0
    report = {"ok": True, "catalog_id": pipeline_catalog().catalog_id}

    async def resolve_image(_self):
        return "sha256:" + "a" * 64

    async def preflight(_self, *_args):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await released.wait()
            if stale_result == "rejected":
                raise PreflightRejected("Old controller's remote rejection")
            if stale_result == "error":
                raise RuntimeError("Old controller's remote outage")
        return report

    monkeypatch.setattr(PipelinePreflight, "resolve_image", resolve_image)
    monkeypatch.setattr(PipelinePreflight, "run", preflight)
    async with pipeline_database() as session:
        _, revision = await published_design(session)
        activation = await PipelineActivations(session, workloads=workloads).submit(
            PipelineActivationRequest(
                revision_id=revision.id,
                bindings={"value": "current"},
                display_name="Lease handoff",
                idempotency_key=f"lease-{stale_result}",
            )
        )

    async with pipeline_database() as old_session:
        old_controller = asyncio.create_task(
            PipelineActivations(old_session, workloads=workloads).advance(activation.id)
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=10)
            async with pipeline_database() as new_session:
                row = await new_session.get(PipelineActivation, activation.id)
                old_token = row.controller_token
                assert old_token is not None
                row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                await new_session.commit()

                # The successor controller really takes the expired lease and
                # completes preflight, then independently advances validation.
                controller = PipelineActivations(new_session, workloads=workloads)
                await controller.advance(activation.id)
                await controller.advance(activation.id)
                row = await new_session.get(
                    PipelineActivation, activation.id, populate_existing=True
                )
                assert row.phase == "starting"
                assert row.controller_token is None
                published_at = row.updated_at
                await new_session.commit()

                released.set()
                await asyncio.wait_for(old_controller, timeout=10)
                row = await new_session.get(
                    PipelineActivation, activation.id, populate_existing=True
                )
                assert row.phase == "starting"
                assert row.preflight == report
                assert row.error is None
                assert not row.cancel_requested
                assert row.controller_token is None
                assert row.lease_expires_at is None
                assert row.updated_at == published_at
                run = await new_session.get(PipelineRun, row.run_id)
                assert run.status == "reserved" and run.ended_at is None
        finally:
            released.set()
            await asyncio.gather(old_controller, return_exceptions=True)


@pytest.mark.asyncio
async def test_running_intent_keeps_claim_when_legacy_status_is_false(
    pipeline_database, monkeypatch
):
    async with pipeline_database() as session:
        _, revision = await published_design(session)
        snapshot = await read_collection_runtime(session)
        topic = next(
            stream.accepted_topic
            for stream in snapshot.catalog.streams()
            if stream.definition.id == "current"
        )
        session.add(
            MonitoringService(
                id="restarting-legacy",
                container_name="restarting-legacy",
                mqtt_topic=[topic],
                status=False,
                desired_state="running",
            )
        )
        await session.commit()
        with pytest.raises(ConflictError, match="only one monitoring service"):
            await PipelineActivations(session).submit(
                PipelineActivationRequest(
                    revision_id=revision.id,
                    bindings={"value": "current"},
                    display_name="Conflicting graph",
                    idempotency_key="restarting-legacy-graph-conflict",
                )
            )
        await session.rollback()
        with pytest.raises(ValueError, match="overlaps active service"):
            await RadarOrchestrationService(session)._assert_topics_available(
                mqtt_topics=[topic], container_name="conflicting-legacy"
            )
        await session.rollback()
        proposed = snapshot.catalog.model_copy(deep=True)
        proposed.document.streams[0].policy = CollectionPolicy(mode="off")
        affected = await SystemCollectionService(session).affected(
            snapshot.catalog, proposed
        )
        assert affected == [{"id": "restarting-legacy", "name": "restarting-legacy"}]
        await session.rollback()
        monkeypatch.setenv("TACTIC_RADAR_MAX_ACTIVE_MONITORS", "1")
        get_tactic_settings.cache_clear()
        with pytest.raises(ConflictError, match="capacity"):
            await PipelineActivations(session).submit(
                PipelineActivationRequest(
                    revision_id=revision.id,
                    bindings={"value": "temperature"},
                    display_name="Capacity conflict",
                    idempotency_key="restarting-legacy-capacity-conflict",
                )
            )


@pytest.mark.asyncio
async def test_runtime_failure_cannot_be_overwritten_by_heartbeat_verification(
    pipeline_database, monkeypatch
):
    entered, released = asyncio.Event(), asyncio.Event()
    async with pipeline_database() as session:
        _, revision = await published_design(session)
        activation = await PipelineActivations(session).submit(
            PipelineActivationRequest(
                revision_id=revision.id,
                bindings={"value": "current"},
                display_name="Fatal heartbeat race",
                idempotency_key="fatal-heartbeat-race",
            )
        )
        row = await session.get(PipelineActivation, activation.id)
        row.phase = "awaiting_heartbeat"
        row.heartbeat_deadline = datetime.now(UTC) + timedelta(minutes=5)
        run = await session.get(PipelineRun, row.run_id)
        run.status = "starting"
        execution = PipelineExecutionConfig.model_validate(run.execution)
        session.add(
            MonitoringService(
                id=row.service_id,
                container_name=row.launch_config["container_name"],
                mqtt_topic=row.launch_config["mqtt_topics"],
                status=True,
                desired_state="running",
                lifecycle_version=1,
                operational_stage="operational",
                operational_updated_at=datetime.now(UTC),
                launch_config=row.launch_config,
            )
        )
        await session.flush()
        session.add(
            RadarRuntimeCheckpoint(
                service_id=row.service_id,
                format_version=1,
                configuration_fingerprint="configuration",
                runtime_fingerprint="runtime",
                processed_count=7,
                saved_at=datetime.now(UTC),
                payload=b"last durable snapshot",
                signature="owned-checkpoint-token",
            )
        )
        await session.commit()

    writer = DatabaseWriter(
        MQTTRadarConfig(pipeline=execution),
        session_factory=pipeline_database,
        managed_checkpoints=True,
        service_id=activation.service_id,
    )
    original_checkpoint = await writer.load_checkpoint(activation.service_id)
    async with pipeline_database() as verifying:
        original_get = verifying.get
        run_reads = 0

        async def get_then_pause(entity, *args, **kwargs):
            nonlocal run_reads
            result = await original_get(entity, *args, **kwargs)
            if entity is PipelineRun:
                run_reads += 1
                if run_reads == 2:  # The phase's read, after lease acquisition commits.
                    entered.set()
                    await released.wait()
            return result

        monkeypatch.setattr(verifying, "get", get_then_pause)
        verification = asyncio.create_task(
            PipelineActivations(verifying).advance(activation.id)
        )
        failure = None
        try:
            await asyncio.wait_for(entered.wait(), timeout=10)
            failure = asyncio.create_task(
                writer.fail_pipeline_run("Real fatal persistence during verification")
            )
            # Verification owns Run before Service. The actual writer owns the
            # checkpoint and must wait for Run, then publish the terminal state.
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(failure), timeout=0.2)
            released.set()
            await asyncio.wait_for(verification, timeout=10)
            await asyncio.wait_for(failure, timeout=10)
        finally:
            released.set()
            await asyncio.gather(
                *(task for task in (verification, failure) if task is not None),
                return_exceptions=True,
            )

    async with pipeline_database() as session:
        run = await session.get(PipelineRun, activation.run_id)
        service = await session.get(MonitoringService, activation.service_id)
        assert run.status == "failed" and run.ended_at is not None
        assert run.error == "Real fatal persistence during verification"
        assert service.operational_stage == "failed"
    assert await writer.load_checkpoint(activation.service_id) == original_checkpoint
    with pytest.raises(RuntimeError, match="running monitor intent"):
        await require_monitor_admission(
            settings=RadarAdmissionSettings(
                SERVICE_ID=activation.service_id, RADAR_LIFECYCLE_VERSION=1
            ),
            session_factory=pipeline_database,
        )


@pytest.mark.asyncio
async def test_setup_form_starts_a_pipeline_while_the_workbench_is_off(
    pipeline_database, monkeypatch
):
    from off_key_core.schemas.radar import FormMonitorConfig
    from off_key_tactic_middleware.services.pipelines.forms import start_form_monitor

    monkeypatch.setenv("TACTIC_PIPELINE_AUTHORING_ENABLED", "false")
    get_tactic_settings.cache_clear()
    async with pipeline_database() as session:
        catalog = (await read_collection_runtime(session)).catalog
        topics = {
            stream.definition.id: stream.accepted_topic
            for stream in catalog.streams(selected_only=True)
        }
        config = FormMonitorConfig(
            container_name="radar-device",
            mqtt_topics=[topics["temperature"], topics["current"]],
            performance_config={"sensor_freshness_seconds": 12},
        )
        with pytest.raises(ConflictError, match="disabled"):
            await PipelineActivations(session).apply(
                PipelineApplyRequest(
                    definition=pipeline_catalog().templates[0].definition,
                    bindings={"value": "current"},
                    display_name="Workbench",
                    idempotency_key="workbench-off",
                )
            )
        await session.rollback()
        activation = await start_form_monitor(session, config)
        run = await session.get(PipelineRun, activation.run_id)
        launch = run.launch_config
        assert launch["display_name"] == "radar-device"
        assert launch["performance_config"]["sensor_freshness_seconds"] == 12
        assert launch["container_name"] == f"pipeline-{activation.service_id}"
        execution = PipelineExecutionConfig.model_validate(run.execution)
        assert {item.reading_id for item in execution.bindings} == {
            "current",
            "temperature",
        }
        keys = [item.input_key for item in execution.bindings]
        assert keys == sorted(keys)
        design = await session.get(
            MonitoringPipeline,
            await session.scalar(
                select(PipelineRevision.pipeline_id).where(
                    PipelineRevision.id == run.revision_id
                )
            ),
        )
        assert design.description == "Created by the monitoring setup form"
        assert (await PipelineLibrary(session).list()).items == []


@pytest.mark.asyncio
async def test_release_converts_a_saved_form_monitor_or_retires_it(pipeline_database):
    from off_key_core.db.models import PipelineRevision
    from off_key_tactic_middleware.services.pipelines.forms import (
        UnconvertibleFormMonitor,
        convert_saved_form_monitor,
    )

    async with pipeline_database() as session:
        catalog = (await read_collection_runtime(session)).catalog
        topics = {
            stream.definition.id: stream.accepted_topic
            for stream in catalog.streams(selected_only=True)
        }
        # Saved by the setup form before every monitor ran as a pipeline.
        saved = {
            "container_name": "radar-device",
            "display_name": "Device",
            "mqtt_topics": [topics["temperature"], topics["current"]],
            "monitoring": {"strategy": "static_baseline"},
            "performance_config": {"sensor_freshness_seconds": 12},
            "mqtt_config": {"qos": 1},
            "pipeline": None,
        }
        launch, metadata = await convert_saved_form_monitor(session, saved)

        assert launch.container_name == "radar-device"
        assert launch.mqtt_config.qos == 1
        assert launch.performance_config.sensor_freshness_seconds == 12
        assert {item.reading_id for item in launch.pipeline.bindings} == {
            "current",
            "temperature",
        }
        assert launch.monitoring.strategy == "static_baseline"
        revision = await session.get(PipelineRevision, launch.pipeline.revision_id)
        assert revision is not None
        assert metadata.collection_fingerprint
        with pytest.raises(UnconvertibleFormMonitor, match="Select these topics"):
            await convert_saved_form_monitor(
                session, saved | {"mqtt_topics": ["telemetry/device/unknown"]}
            )
