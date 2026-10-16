"""Versioned pipeline library and non-mutating service projections."""

from datetime import UTC, datetime
from uuid import uuid4

from off_key_core.db.collection import lock_collection_configuration
from off_key_core.db.maintenance import require_application_writes
from off_key_core.db.models import (
    MonitoringPipeline,
    MonitoringService,
    PipelineRevision,
    PipelineRun,
)
from off_key_core.models.pipeline_reports import bounded_validation_report
from off_key_core.models.pipelines import (
    compile_pipeline,
    pipeline_catalog_id,
    validate_pipeline,
)
from off_key_core.schemas.pipelines import (
    PipelineCreate,
    PipelineDefinition,
    PipelineDraftSave,
    PipelineLayout,
    PipelineMetadataChange,
    PipelinePublish,
    PipelineRevisionView,
    PipelineRunView,
    PipelineServiceView,
    PipelineView,
)
from off_key_core.utils.json_budget import bounded_utf8_text
from sqlalchemy import select

from ...config.config import get_tactic_settings
from ...domain import ConflictError, NotFoundError, ValidationError


def require_authoring() -> None:
    if not get_tactic_settings().config.pipeline_authoring_enabled:
        raise ConflictError("Pipeline authoring is disabled by the operator")


def revision_view(revision) -> PipelineRevisionView:
    return PipelineRevisionView.model_validate(
        {key: getattr(revision, key) for key in PipelineRevisionView.model_fields}
    )


def run_view(run) -> PipelineRunView:
    return PipelineRunView.model_validate(
        {key: getattr(run, key) for key in PipelineRunView.model_fields}
    )


class PipelineLibrary:
    def __init__(self, session):
        self.session = session

    async def list(self):
        rows = list(
            (
                await self.session.scalars(
                    select(MonitoringPipeline).order_by(
                        MonitoringPipeline.updated_at.desc()
                    )
                )
            ).all()
        )
        return [await self._view(row) for row in rows]

    async def get(self, identifier: str):
        return await self._view(await self._row(identifier))

    async def _row(self, identifier: str, *, lock: bool = False):
        row = await self.session.get(
            MonitoringPipeline, identifier, with_for_update=lock, populate_existing=True
        )
        if row is None:
            raise NotFoundError("Pipeline design not found")
        return row

    async def _view(self, row):
        revisions = await self.session.scalars(
            select(PipelineRevision)
            .where(PipelineRevision.pipeline_id == row.id)
            .order_by(PipelineRevision.number.desc())
        )
        return PipelineView(
            id=row.id,
            name=row.name,
            description=row.description,
            archived=row.archived,
            version=row.version,
            draft=row.draft,
            layout=row.layout,
            revisions=[revision_view(item) for item in revisions],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _write(self):
        require_authoring()
        await lock_collection_configuration(self.session)
        await require_application_writes(self.session)

    async def create(self, change: PipelineCreate):
        await self._write()
        now = datetime.now(UTC)
        row = MonitoringPipeline(
            id=str(uuid4()),
            name=change.name.strip(),
            description=change.description,
            archived=False,
            version=1,
            draft=change.definition.model_dump(mode="json"),
            layout=change.layout.model_dump(mode="json"),
            created_at=now,
            updated_at=now,
        )
        if not row.name:
            raise ValidationError("Pipeline name must not be empty")
        self.session.add(row)
        await self.session.commit()
        return await self._view(row)

    @staticmethod
    def _version(row, expected):
        if row.version != expected:
            raise ConflictError("This design changed; reload before saving")

    async def save_draft(self, identifier: str, change: PipelineDraftSave):
        await self._write()
        row = await self._row(identifier, lock=True)
        self._version(row, change.expected_version)
        row.draft = change.definition.model_dump(mode="json")
        row.layout = change.layout.model_dump(mode="json")
        row.version += 1
        row.updated_at = datetime.now(UTC)
        await self.session.commit()
        return await self._view(row)

    async def metadata(self, identifier: str, change: PipelineMetadataChange):
        await self._write()
        row = await self._row(identifier, lock=True)
        self._version(row, change.expected_version)
        if not change.name.strip():
            raise ValidationError("Pipeline name must not be empty")
        row.name, row.description, row.archived = (
            change.name.strip(),
            change.description,
            change.archived,
        )
        row.version += 1
        row.updated_at = datetime.now(UTC)
        await self.session.commit()
        return await self._view(row)

    async def publish(self, identifier: str, change: PipelinePublish):
        await self._write()
        row = await self._row(identifier, lock=True)
        self._version(row, change.expected_version)
        if row.archived:
            raise ConflictError("Restore an archived design before publishing")
        try:
            compiled = compile_pipeline(PipelineDefinition.model_validate(row.draft))
        except ValueError as exc:
            raise ValidationError(bounded_utf8_text(str(exc), 4096)) from exc
        prior = await self.session.scalar(
            select(PipelineRevision)
            .where(PipelineRevision.pipeline_id == identifier)
            .order_by(PipelineRevision.number.desc())
            .limit(1)
        )
        revision = PipelineRevision(
            id=str(uuid4()),
            pipeline_id=identifier,
            number=prior.number + 1 if prior else 1,
            definition=compiled.definition.model_dump(mode="json"),
            fingerprint=compiled.fingerprint,
            catalog_id=pipeline_catalog_id(),
            created_at=datetime.now(UTC),
        )
        self.session.add(revision)
        row.version += 1
        row.updated_at = datetime.now(UTC)
        await self.session.commit()
        return revision_view(revision)

    async def validate(self, identifier: str, definition, selected_node_id=None):
        await self._row(identifier)
        return bounded_validation_report(
            validate_pipeline(definition), selected_node_id
        )

    async def revisions(self, identifier: str):
        return (await self.get(identifier)).revisions

    async def revision(self, identifier: str, revision_id: str):
        revision = await self.session.get(PipelineRevision, revision_id)
        if revision is None or revision.pipeline_id != identifier:
            raise NotFoundError("Pipeline revision not found")
        return revision_view(revision)

    async def service(self, service_id: str, selected_node_id=None):
        run = await self.session.scalar(
            select(PipelineRun).where(PipelineRun.service_id == service_id)
        )
        service = await self.session.get(MonitoringService, service_id)
        if run is None and service is None:
            raise NotFoundError("Monitoring service not found")
        config = run.launch_config if run else service.launch_config
        execution = config.get("pipeline") if config else None
        if execution:
            definition = PipelineDefinition.model_validate(execution["definition"])
        else:
            definition = legacy_definition(config or {})
        validation = bounded_validation_report(
            validate_pipeline(definition), selected_node_id
        )
        history = []
        cursor = run
        visited = set()
        while cursor is not None and cursor.id not in visited:
            visited.add(cursor.id)
            history.append(run_view(cursor))
            cursor = (
                await self.session.get(PipelineRun, cursor.predecessor_run_id)
                if cursor.predecessor_run_id
                else None
            )
        return PipelineServiceView(
            run=run_view(run) if run else None,
            history=history,
            definition=definition,
            layout=PipelineLayout.model_validate(run.layout or {})
            if run
            else PipelineLayout(),
            legacy=execution is None,
            validation=validation,
        )

    async def layout(self, service_id: str, layout: PipelineLayout):
        await self._write()
        run = await self.session.scalar(
            select(PipelineRun)
            .where(PipelineRun.service_id == service_id)
            .with_for_update()
        )
        if run is None:
            raise NotFoundError("Pipeline run not found")
        current = PipelineLayout.model_validate(run.layout or {})
        if layout.version != current.version:
            raise ConflictError("Pipeline arrangement changed; reload before saving")
        layout = layout.model_copy(update={"version": current.version + 1})
        run.layout = layout.model_dump(mode="json")
        await self.session.commit()
        return layout


def legacy_definition(config: dict) -> PipelineDefinition:
    """Presentation of existing saved monitor semantics, never an implicit migration."""
    from off_key_core.utils.mqtt_topics import derive_monitoring_sensor_keys

    from .release import normalize_saved_launch

    # Read reviewed older launch schemas without changing their saved provenance.
    parsed = normalize_saved_launch(config)
    keys = derive_monitoring_sensor_keys(
        parsed.mqtt_topics,
        sensor_key_strategy=parsed.performance_config.sensor_key_strategy,
    )
    slots = [
        {"id": f"input_{index + 1}", "label": key} for index, key in enumerate(keys)
    ]
    nodes = [{"id": "input", "kind": "source", "component": "source.aligned"}]
    previous = "input"
    edges = []
    for index, step in enumerate(getattr(parsed.monitoring, "preprocessing_steps", [])):
        params = step.model_dump(mode="json")
        kind = params.pop("type")
        node_id = f"transform_{index + 1}"
        component = (
            f"adaptive.{kind if kind != 'incremental_pca' else 'uncentered_pca'}"
        )
        nodes.append(
            {
                "id": node_id,
                "kind": "transform",
                "component": component,
                "params": params,
            }
        )
        edges.append({"source": previous, "target": node_id})
        previous = node_id
    policy = (
        "policy.martingale"
        if parsed.monitoring.strategy == "static_baseline"
        else "policy.quantile"
    )
    policy_params = (
        parsed.monitoring.martingale_config
        if parsed.monitoring.strategy == "static_baseline"
        else parsed.monitoring.threshold_config
    )
    nodes.extend(
        [
            {
                "id": "detector",
                "kind": "detector",
                "component": f"detector:{parsed.monitoring.model_type}",
                "params": parsed.monitoring.model_params,
            },
            {
                "id": "policy",
                "kind": "policy",
                "component": policy,
                "params": policy_params.model_dump(mode="json"),
            },
            {"id": "output", "kind": "output", "component": "output.evidence"},
        ]
    )
    edges.extend(
        [
            {"source": previous, "target": "detector"},
            {"source": "detector", "target": "policy"},
            {"source": "policy", "target": "output"},
        ]
    )
    return PipelineDefinition.model_validate(
        {
            "strategy": parsed.monitoring.strategy,
            "input_slots": slots,
            "nodes": nodes,
            "edges": edges,
            "settings": {
                "training_window_size": parsed.monitoring.training_window_size,
                "calibration_window_size": parsed.monitoring.calibration_window_size,
                "seed": getattr(parsed.monitoring, "seed", 42),
            },
        }
    )
