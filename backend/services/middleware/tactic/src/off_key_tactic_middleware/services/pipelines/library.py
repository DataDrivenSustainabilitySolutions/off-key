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
from off_key_core.models.pipeline_reports import (
    bounded_validation_report,
    focused_validation_report,
)
from off_key_core.models.pipelines import (
    compile_pipeline,
    lower_form_monitor,
    pipeline_catalog_id,
    validate_pipeline,
)
from off_key_core.schemas.pipelines import (
    PipelineCreate,
    PipelineDefinition,
    PipelineDraftSave,
    PipelineHistoryQuery,
    PipelineLayout,
    PipelineListQuery,
    PipelineMetadataChange,
    PipelinePublish,
    PipelineRevisionQuery,
    PipelineRevisionView,
    PipelineRunView,
    PipelineServiceView,
    PipelineView,
)
from off_key_core.utils.json_budget import bounded_utf8_text
from sqlalchemy import select

from ...config.config import get_tactic_settings
from ...domain import ConflictError, NotFoundError, ValidationError
from .queries import list_designs, list_revisions, run_history


def require_authoring() -> None:
    if not get_tactic_settings().config.pipeline_authoring_enabled:
        raise ConflictError("Pipeline authoring is disabled by the operator")


def revision_view(revision) -> PipelineRevisionView:
    return PipelineRevisionView.model_validate(
        {key: getattr(revision, key) for key in PipelineRevisionView.model_fields}
    )


def run_view(run, pipeline_id=None) -> PipelineRunView:
    return PipelineRunView.model_validate(
        {
            key: getattr(run, key)
            for key in PipelineRunView.model_fields
            if key != "pipeline_id"
        }
        | {"pipeline_id": pipeline_id}
    )


class PipelineLibrary:
    def __init__(self, session):
        self.session = session

    async def list(self, query: PipelineListQuery | None = None):
        return await list_designs(self.session, query or PipelineListQuery())

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
        revisions = await list_revisions(self.session, row.id, PipelineRevisionQuery())
        return PipelineView(
            id=row.id,
            name=row.name,
            description=row.description,
            archived=row.archived,
            is_template=row.is_template,
            version=row.version,
            draft=row.draft,
            layout=row.layout,
            revisions=revisions.items,
            revision_next_before=revisions.next_before,
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
        if change.name is not None:
            if not change.name.strip():
                raise ValidationError("Pipeline name must not be empty")
            row.name = change.name.strip()
        if change.description is not None:
            row.description = change.description
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

    async def revisions(
        self, identifier: str, query: PipelineRevisionQuery | None = None
    ):
        await self._row(identifier)
        return await list_revisions(
            self.session, identifier, query or PipelineRevisionQuery()
        )

    async def revision(self, identifier: str, revision_id: str):
        revision = await self.session.get(PipelineRevision, revision_id)
        if revision is None or revision.pipeline_id != identifier:
            raise NotFoundError("Pipeline revision not found")
        return revision_view(revision)

    async def pipeline_state(self, service_id: str):
        service = await self.session.get(MonitoringService, service_id)
        if service is None:
            raise NotFoundError("Monitoring service not found")
        return (service.operational_status or {}).get("pipeline_state")

    async def selected_state(self, service_id: str | None):
        """The workspace's selected service state; a missing selection is None."""
        if not service_id:
            return None
        service = await self.session.get(MonitoringService, service_id)
        if service is None:
            return None
        return (service.operational_status or {}).get("pipeline_state")

    async def _service_source(self, service_id):
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
        return run, definition, execution

    async def service(self, service_id: str, selected_node_id=None):
        run, definition, execution = await self._service_source(service_id)
        validation = bounded_validation_report(
            validate_pipeline(definition), selected_node_id
        )
        history = await run_history(self.session, service_id, PipelineHistoryQuery())
        pipeline_id = (
            await self.session.scalar(
                select(PipelineRevision.pipeline_id).where(
                    PipelineRevision.id == run.revision_id
                )
            )
            if run and run.revision_id
            else None
        )
        return PipelineServiceView(
            run=run_view(run, pipeline_id) if run else None,
            history=history.items,
            history_next_service_id=history.next_service_id,
            definition=definition,
            layout=PipelineLayout.model_validate(run.layout or {})
            if run
            else PipelineLayout(),
            legacy=execution is None,
            validation=validation,
        )

    async def history(self, service_id, query: PipelineHistoryQuery):
        page = await run_history(self.session, service_id, query)
        if (
            not page.items
            and await self.session.get(MonitoringService, service_id) is None
        ):
            raise NotFoundError("Monitoring service not found")
        return page

    async def service_metadata(self, service_id, selected_node_id):
        _, definition, _ = await self._service_source(service_id)
        return focused_validation_report(
            validate_pipeline(definition), selected_node_id
        )

    async def revision_metadata(self, pipeline_id, revision_id, selected_node_id):
        revision = await self.revision(pipeline_id, revision_id)
        return focused_validation_report(
            validate_pipeline(revision.definition), selected_node_id
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
    """The graph equivalent of a saved form-configured monitor."""
    from .release import normalize_saved_launch

    # Read reviewed older launch schemas without changing their saved provenance.
    return lower_form_monitor(normalize_saved_launch(config))
