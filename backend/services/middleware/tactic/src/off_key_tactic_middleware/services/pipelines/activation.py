"""Durable, retryable replacement with source claims surviving remote uncertainty."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from off_key_core.config.logs import logger
from off_key_core.db.collection import lock_collection_configuration
from off_key_core.db.collection_runtime import (
    monitoring_collection_fingerprint,
    read_collection_runtime,
)
from off_key_core.db.maintenance import require_application_writes
from off_key_core.db.models import (
    MonitoringPipeline,
    MonitoringService,
    PipelineActivation,
    PipelineRevision,
    PipelineRun,
    SystemConfiguration,
)
from off_key_core.db.pipeline_claims import (
    TERMINAL_ACTIVATION_PHASES,
    monitor_claim_condition,
    pending_activations,
)
from off_key_core.models.pipelines import (
    compile_pipeline,
    derive_monitoring_config,
    execution_fingerprint,
    pipeline_catalog_id,
)
from off_key_core.schemas.pipelines import (
    BoundInput,
    PipelineActivationRequest,
    PipelineActivationView,
    PipelineBindingMetadata,
    PipelineDefinition,
    PipelineExecutionConfig,
    PipelineReadingMetadata,
)
from off_key_core.schemas.radar import (
    PerformanceConfig,
    RadarOperationalStatus,
    RadarStartConfig,
)
from off_key_core.utils.mqtt_topics import (
    derive_monitoring_sensor_keys,
    mqtt_topic_filters_overlap,
)
from sqlalchemy import select

from ...config.config import get_tactic_settings
from ...domain import ConflictError, NotFoundError, ValidationError
from ..orchestration.radar import RadarOrchestrationService
from ..orchestration.radar_workloads import RadarWorkloadManager, get_async_docker
from .library import require_authoring
from .preflight import PipelinePreflight, PreflightRejected


def activation_view(row):
    return PipelineActivationView.model_validate(
        {key: getattr(row, key) for key in PipelineActivationView.model_fields}
    )


class ActivationOwnershipLost(RuntimeError):
    """A delayed controller must leave the newer durable activation untouched."""


class PipelineActivations:
    def __init__(self, session, registry=None, workloads=None):
        self.session = session
        self.registry = registry
        self._workloads = workloads

    @property
    def workloads(self):
        if self._workloads is None:
            self._workloads = RadarWorkloadManager(get_async_docker())
        return self._workloads

    def _orchestration(self):
        return RadarOrchestrationService(
            self.session, self.registry, workloads=self.workloads
        )

    async def get(self, identifier):
        return activation_view(await self._row(identifier))

    async def _row(self, identifier, *, lock=False):
        row = await self.session.get(
            PipelineActivation, identifier, with_for_update=lock, populate_existing=True
        )
        if row is None:
            raise NotFoundError("Pipeline activation not found")
        return row

    async def _owned_row(self, identifier, token, phase):
        # Keep the same lock order as submit/advance/cancel. Remote calls commit
        # before waiting; every resumed transition must reclaim this fence.
        await lock_collection_configuration(self.session)
        await require_application_writes(self.session)
        row = await self._row(identifier, lock=True)
        if (
            row.controller_token != token
            or row.phase != phase
            or row.lease_expires_at is None
            or row.lease_expires_at <= datetime.now(UTC)
        ):
            raise ActivationOwnershipLost("Pipeline controller lease was superseded")
        return row

    async def submit(self, request: PipelineActivationRequest):
        require_authoring()
        await lock_collection_configuration(self.session)
        await require_application_writes(self.session)
        request_hash = hashlib.sha256(
            json.dumps(
                request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        existing = await self.session.scalar(
            select(PipelineActivation).where(
                PipelineActivation.idempotency_key == request.idempotency_key
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ConflictError(
                    "Idempotency key already identifies a different activation"
                )
            return activation_view(existing)
        revision, design, definition = await self._published_design(request)
        predecessor = await self._predecessor(request)
        performance, topics, bindings, snapshot = await self._bindings(
            request, definition
        )
        claims = await self._claims(request, predecessor, topics)
        now = datetime.now(UTC)
        identifier, service_id, run_id = str(uuid4()), str(uuid4()), str(uuid4())
        execution = PipelineExecutionConfig(
            definition=definition,
            bindings=bindings,
            revision_id=revision.id,
            run_id=run_id,
            fingerprint=execution_fingerprint(definition, bindings),
        )
        config = RadarStartConfig(
            container_name=f"pipeline-{service_id}",
            display_name=request.display_name,
            mqtt_topics=topics,
            monitoring=derive_monitoring_config(definition),
            performance_config=performance,
            pipeline=execution,
        )
        collection_fingerprint = await monitoring_collection_fingerprint(
            self.session, topics
        )
        predecessor_run = await self._predecessor_run(predecessor, now)
        launch = config.model_dump(mode="json")
        run = PipelineRun(
            id=run_id,
            service_id=service_id,
            revision_id=revision.id,
            predecessor_run_id=predecessor_run.id if predecessor_run else None,
            execution=execution.model_dump(mode="json"),
            launch_config=launch,
            layout=design.layout,
            binding_metadata=(
                await self._binding_metadata(bindings, snapshot, collection_fingerprint)
            ).model_dump(mode="json"),
            status="reserved",
            created_at=now,
        )
        self.session.add(run)
        await self.session.flush()
        row = PipelineActivation(
            id=identifier,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            revision_id=revision.id,
            service_id=service_id,
            run_id=run_id,
            predecessor_service_id=request.replace_service_id,
            predecessor_lifecycle_version=predecessor.lifecycle_version
            if predecessor
            else None,
            retirement_started=False,
            phase="requested",
            claim_topics=claims,
            collection_fingerprint=collection_fingerprint,
            launch_config=launch,
            cancel_requested=False,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        await self.session.commit()
        return activation_view(row)

    async def _published_design(self, request):
        revision = await self.session.get(PipelineRevision, request.revision_id)
        if revision is None:
            raise NotFoundError("Pipeline revision not found")
        design = await self.session.get(MonitoringPipeline, revision.pipeline_id)
        if design.archived:
            raise ConflictError("Restore the archived design before activation")
        try:
            compiled = compile_pipeline(
                PipelineDefinition.model_validate(revision.definition)
            )
        except ValueError as exc:
            raise ConflictError(
                "Published component contracts are no longer supported; "
                "publish a validated revision"
            ) from exc
        if compiled.fingerprint != revision.fingerprint:
            raise ConflictError(
                "Published executable normalization changed; "
                "publish a validated revision"
            )
        return revision, design, compiled.definition

    async def _predecessor(self, request):
        predecessor = (
            await self.session.get(MonitoringService, request.replace_service_id)
            if request.replace_service_id
            else None
        )
        if request.replace_service_id and (
            predecessor is None
            or not predecessor.status
            or predecessor.desired_state != "running"
            or predecessor.stop_requested_at is not None
        ):
            raise ConflictError("The service being replaced is no longer running")
        if predecessor is not None and not predecessor.launch_config:
            raise ConflictError(
                "Capture the existing monitor configuration before replacement"
            )
        return predecessor

    async def _bindings(self, request, definition):
        snapshot = await read_collection_runtime(self.session)
        if (
            snapshot.collection.get("revision") != snapshot.revision
            or snapshot.collection.get("status") != "applied"
        ):
            raise ConflictError("Wait for the collection configuration to be applied")
        streams = {
            stream.definition.id: stream
            for stream in snapshot.catalog.streams(selected_only=True)
            if stream.value_type == "number"
        }
        if set(request.bindings) != {slot.id for slot in definition.input_slots}:
            raise ValidationError("Bind every named input slot exactly once")
        if len(set(request.bindings.values())) != len(request.bindings):
            raise ValidationError("Each input must bind a distinct numeric reading")
        try:
            selected = {
                slot: streams[reading] for slot, reading in request.bindings.items()
            }
        except KeyError as exc:
            raise ValidationError(
                "Input bindings require selected numeric catalogue readings"
            ) from exc
        performance = PerformanceConfig()
        topics = [selected[slot.id].accepted_topic for slot in definition.input_slots]
        keys = derive_monitoring_sensor_keys(
            topics, sensor_key_strategy=performance.sensor_key_strategy
        )
        key_by_topic = dict(zip(topics, keys, strict=True))
        bindings = [
            BoundInput(
                slot_id=slot.id,
                reading_id=selected[slot.id].definition.id,
                entity_id=selected[slot.id].charger_id,
                accepted_topic=selected[slot.id].accepted_topic,
                input_key=key_by_topic[selected[slot.id].accepted_topic],
                unit=selected[slot.id].definition.unit,
            )
            for slot in definition.input_slots
        ]
        return performance, topics, bindings, snapshot

    async def _binding_metadata(self, bindings, snapshot, fingerprint):
        document = snapshot.catalog.document
        readings = {item.id: item for item in document.streams}
        devices = {item.id: item for item in document.devices}
        sources = {item.id: item for item in document.connections}
        metadata = []
        for binding in bindings:
            reading = readings[binding.reading_id]
            source = sources[reading.connection_id]
            device = devices.get(reading.device_id)
            metadata.append(
                PipelineReadingMetadata(
                    slot_id=binding.slot_id,
                    reading_id=reading.id,
                    label=reading.label,
                    unit=reading.unit,
                    entity_id=binding.entity_id,
                    device_id=reading.device_id,
                    entity_label=device.label if device else source.label,
                    source_id=source.id,
                    source_label=source.label,
                    accepted_topic=binding.accepted_topic,
                    collection_policy=reading.policy or document.default_policy,
                )
            )
        system_revision = await self.session.scalar(
            select(SystemConfiguration.revision).where(SystemConfiguration.id == 1)
        )
        return PipelineBindingMetadata(
            system_revision=system_revision,
            collection_revision=snapshot.revision,
            collection_generation=snapshot.catalog.generation,
            collection_fingerprint=fingerprint,
            readings=metadata,
        )

    async def _claims(self, request, predecessor, topics):
        pending = await pending_activations(self.session)
        if any(
            item.predecessor_service_id == request.replace_service_id
            and request.replace_service_id
            for item in pending
        ):
            raise ConflictError("Another activation already replaces this service")
        claims = sorted(
            set(topics) | set(predecessor.mqtt_topic if predecessor else [])
        )
        if any(
            mqtt_topic_filters_overlap(topic, claimed)
            for item in pending
            for topic in claims
            for claimed in item.claim_topics
        ):
            raise ConflictError(
                "A pending activation already reserves one or more inputs"
            )
        active = list(
            (
                await self.session.scalars(
                    select(MonitoringService).where(monitor_claim_condition())
                )
            ).all()
        )
        if any(
            item.id != request.replace_service_id
            and mqtt_topic_filters_overlap(topic, claimed)
            for item in active
            for topic in claims
            for claimed in item.mqtt_topic
        ):
            raise ConflictError("A reading can belong to only one monitoring service")
        owners = (
            {item.id for item in active}
            - {item.predecessor_service_id for item in pending}
            - {request.replace_service_id}
        )
        owners |= {item.service_id for item in pending}
        if len(owners) >= get_tactic_settings().config.radar_max_active_monitors:
            raise ConflictError(
                "RADAR capacity reached; stop another monitor before activation"
            )
        return claims

    async def _predecessor_run(self, predecessor, now):
        predecessor_run = (
            await self.session.scalar(
                select(PipelineRun).where(PipelineRun.service_id == predecessor.id)
            )
            if predecessor
            else None
        )
        if predecessor is not None and predecessor_run is None:
            predecessor_run = PipelineRun(
                id=str(uuid4()),
                service_id=predecessor.id,
                revision_id=None,
                execution=None,
                launch_config=predecessor.launch_config,
                layout={},
                status="running",
                created_at=now,
            )
            self.session.add(predecessor_run)
            await self.session.flush()
        return predecessor_run

    async def cancel(self, identifier):
        await lock_collection_configuration(self.session)
        await require_application_writes(self.session)
        row = await self._row(identifier, lock=True)
        if row.phase not in TERMINAL_ACTIVATION_PHASES:
            row.cancel_requested = True
            row.updated_at = datetime.now(UTC)
            await self.session.commit()
        return activation_view(row)

    async def advance(self, identifier):
        await lock_collection_configuration(self.session)
        await require_application_writes(self.session)
        row = await self._row(identifier, lock=True)
        now = datetime.now(UTC)
        if row.phase in TERMINAL_ACTIVATION_PHASES or (
            row.controller_token and row.lease_expires_at and row.lease_expires_at > now
        ):
            await self.session.commit()
            return
        token = str(uuid4())
        row.controller_token = token
        row.lease_expires_at = now + timedelta(
            seconds=get_tactic_settings().config.pipeline_preflight_timeout_seconds
            + 120
        )
        run = await self.session.get(PipelineRun, row.run_id, populate_existing=True)
        if run.ended_at is not None:
            row.cancel_requested = True
            row.error = run.error or row.error
        if row.cancel_requested:
            row.phase = "cancelling"
        elif row.phase == "requested":
            row.phase = "preflighting"
        phase = row.phase
        await self.session.commit()
        try:
            operation = {
                "preflighting": self._preflight,
                "validated": self._validated,
                "retiring": self._retire,
                "starting": self._start,
                "awaiting_heartbeat": self._verify,
                "cancelling": self._cancel,
            }[phase]
            await operation(row, token)
        except ActivationOwnershipLost:
            await self.session.rollback()
        except PreflightRejected as exc:
            await self._record_controller_error(
                identifier, token, phase, exc, reject=True
            )
        except Exception as exc:
            await self._record_controller_error(identifier, token, phase, exc)
        finally:
            await self.session.rollback()
            await lock_collection_configuration(self.session)
            current = await self._row(identifier, lock=True)
            if current.controller_token == token:
                current.controller_token = None
                current.lease_expires_at = None
                current.updated_at = datetime.now(UTC)
            await self.session.commit()

    async def _record_controller_error(
        self, identifier, token, phase, error, *, reject=False
    ):
        await self.session.rollback()
        try:
            current = await self._owned_row(identifier, token, phase)
        except ActivationOwnershipLost:
            return
        current.error = (str(error) if reject else f"{type(error).__name__}: {error}")[
            :4000
        ]
        if reject:
            current.cancel_requested = True
            current.phase = "cancelling"
        await self.session.commit()
        if not reject:
            logger.exception(
                "Pipeline activation requires retry activation_id=%s", identifier
            )

    async def _validated(self, row, token):
        row = await self._owned_row(row.id, token, "validated")
        config = RadarStartConfig.model_validate(row.launch_config)
        fingerprint = await monitoring_collection_fingerprint(
            self.session, config.mqtt_topics
        )
        if fingerprint != row.collection_fingerprint:
            raise PreflightRejected("Inputs changed after runtime preflight")
        row.phase = (
            "cancelling"
            if row.cancel_requested
            else "retiring"
            if row.predecessor_service_id
            else "starting"
        )
        await self.session.commit()

    async def _preflight(self, row, token):
        row = await self._owned_row(row.id, token, "preflighting")
        validator = PipelinePreflight(self.workloads)
        await self.session.commit()
        if row.image_digest is None:
            image = await validator.resolve_image()
            row = await self._owned_row(row.id, token, "preflighting")
            row.image_digest = image
            config = RadarStartConfig.model_validate(row.launch_config).model_copy(
                update={"runtime_image": image}
            )
            row.launch_config = config.model_dump(mode="json")
            run = await self.session.get(PipelineRun, row.run_id)
            run.launch_config = row.launch_config
            await self.session.commit()
        config = RadarStartConfig.model_validate(row.launch_config)
        report = await validator.run(row.id, config.pipeline, row.image_digest)
        row = await self._owned_row(row.id, token, "preflighting")
        expected = await monitoring_collection_fingerprint(
            self.session, config.mqtt_topics
        )
        if (
            expected != row.collection_fingerprint
            or report["catalog_id"] != pipeline_catalog_id()
        ):
            raise PreflightRejected(
                "Inputs or runtime catalogue changed during preflight"
            )
        row.preflight = report
        row.error = None
        row.phase = "cancelling" if row.cancel_requested else "validated"
        await self.session.commit()

    async def _retire(self, row, token):
        row = await self._owned_row(row.id, token, "retiring")
        if row.cancel_requested:
            row.phase = "cancelling"
            await self.session.commit()
            return
        predecessor = await self.session.get(
            MonitoringService, row.predecessor_service_id
        )
        if not row.retirement_started:
            if (
                predecessor is None
                or predecessor.lifecycle_version != row.predecessor_lifecycle_version
                or predecessor.desired_state != "running"
                or predecessor.stop_requested_at is not None
            ):
                raise PreflightRejected(
                    "The predecessor changed after activation was requested"
                )
            row.retirement_started = True
        elif predecessor is not None and (
            predecessor.lifecycle_version != row.predecessor_lifecycle_version + 1
            or predecessor.desired_state != "deleted"
        ):
            raise PreflightRejected(
                "A newer lifecycle request superseded predecessor retirement"
            )
        if predecessor is not None:
            orchestration = self._orchestration()
            if not await orchestration._delete_service(predecessor):
                raise RuntimeError("Predecessor shutdown is not yet confirmed")
        else:
            await self.session.commit()
            await self.workloads.remove_intent(row.predecessor_service_id, None)
        row = await self._owned_row(row.id, token, "retiring")
        row.phase = "cancelling" if row.cancel_requested else "starting"
        row.error = None
        await self.session.commit()

    async def _start(self, row, token):
        row = await self._owned_row(row.id, token, "starting")
        config = RadarStartConfig.model_validate(row.launch_config)
        await self.session.commit()
        orchestration = self._orchestration()
        await orchestration.create_radar_service(
            config, activation_id=row.id, execution_service_id=row.service_id
        )
        row = await self._owned_row(row.id, token, "starting")
        row.phase = "cancelling" if row.cancel_requested else "awaiting_heartbeat"
        row.heartbeat_deadline = datetime.now(UTC) + timedelta(
            seconds=get_tactic_settings().config.pipeline_heartbeat_timeout_seconds
        )
        row.error = None
        run = await self.session.get(
            PipelineRun, row.run_id, with_for_update=True, populate_existing=True
        )
        if run.ended_at is None and run.status != "failed":
            run.status = "starting"
        else:
            row.cancel_requested = True
            row.phase = "cancelling"
            row.error = run.error or "Successor execution ended during startup"
        await self.session.commit()

    async def _verify(self, row, token):
        row = await self._owned_row(row.id, token, "awaiting_heartbeat")
        run = await self.session.get(
            PipelineRun, row.run_id, with_for_update=True, populate_existing=True
        )
        service = await self.session.get(
            MonitoringService,
            row.service_id,
            with_for_update=True,
            populate_existing=True,
        )
        now = datetime.now(UTC)
        first_heartbeat = (
            (
                RadarOperationalStatus.model_validate(
                    service.operational_status or {}
                ).first_heartbeat_at
                or service.operational_updated_at
            )
            if service
            else None
        )
        healthy = (
            service is not None
            and service.operational_updated_at is not None
            and (now - service.operational_updated_at).total_seconds() <= 30
            and first_heartbeat is not None
            and (
                row.heartbeat_deadline is None
                or first_heartbeat <= row.heartbeat_deadline
            )
        )
        if (
            service is None
            or run.ended_at is not None
            or service.desired_state != "running"
            or service.stop_requested_at is not None
        ):
            row.cancel_requested = True
            row.phase = "cancelling"
        elif service.operational_stage == "failed":
            row.error = "Successor reported a failed runtime"
            row.cancel_requested = True
            row.phase = "cancelling"
        elif healthy:
            row.phase = "succeeded"
            row.error = None
            run.status = "running"
        elif row.heartbeat_deadline is not None and now >= row.heartbeat_deadline:
            row.error = (
                "Successor did not report a healthy heartbeat "
                "before its startup deadline"
            )
            row.cancel_requested = True
            row.phase = "cancelling"
        await self.session.commit()

    async def _cancel(self, row, token):
        row = await self._owned_row(row.id, token, "cancelling")
        run = await self.session.get(
            PipelineRun, row.run_id, with_for_update=True, populate_existing=True
        )
        if run.ended_at is None and run.status != "failed":
            run.status = "failed" if row.error else "cancelled"
            run.error = row.error
            run.ended_at = datetime.now(UTC)
        await self.session.commit()
        row = await self._owned_row(row.id, token, "cancelling")
        service = await self.session.get(MonitoringService, row.service_id)
        if service is not None:
            if not await self._orchestration()._delete_service(service):
                raise RuntimeError("Cancelled successor shutdown is not yet confirmed")
        else:
            await self.session.commit()
            await self.workloads.remove_intent(row.service_id, None)
        row = await self._owned_row(row.id, token, "cancelling")
        name = f"radar-preflight-{row.id}"
        await self.session.commit()
        collection = (
            self.workloads.async_docker.client.services
            if await self.workloads._is_swarm_manager()
            else self.workloads.async_docker.client.containers
        )
        import docker

        try:
            preflight = await self.workloads.async_docker.run(collection.get, name)
        except docker.errors.NotFound:
            pass
        else:
            PipelinePreflight.validate_cleanup_identity(preflight, row.id)
            await self.workloads.remove(preflight.id)
        row = await self._owned_row(row.id, token, "cancelling")
        row.phase = "failed" if row.error else "cancelled"
        await self.session.commit()
