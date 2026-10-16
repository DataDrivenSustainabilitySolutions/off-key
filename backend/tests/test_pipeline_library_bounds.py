"""Versioned writes and bounded projections against real PostgreSQL."""

import importlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from off_key_core.db.models import MonitoringPipeline, PipelineRevision, PipelineRun
from off_key_core.db.pipeline_locks import complete_stopped_runs, lock_execution_records
from off_key_core.models.pipelines import compile_pipeline, pipeline_catalog_id
from off_key_core.schemas.pipelines import (
    PipelineActivationRequest,
    PipelineCreate,
    PipelineDraftSave,
    PipelineHistoryQuery,
    PipelineListQuery,
    PipelineRevisionQuery,
)
from off_key_tactic_middleware.domain import ConflictError, ValidationError
from off_key_tactic_middleware.services.pipelines.activation import PipelineActivations
from off_key_tactic_middleware.services.pipelines.library import PipelineLibrary
from sqlalchemy import event

from . import test_monitoring_pipelines_integration as integration
from .test_pipeline_report_bounds import maximum_definition

pipeline_database = integration.pipeline_database


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("running", "stopped"),
        ("failed", "failed"),
        ("cancelled", "cancelled"),
    ],
)
async def test_shared_stop_transition_preserves_outcome_and_first_end_time(
    pipeline_database, status, expected
):
    async with pipeline_database() as session:
        row = PipelineRun(
            id=str(uuid4()),
            service_id="terminal-" + status,
            execution=None,
            launch_config={},
            layout={},
            status=status,
            error="Retained diagnostic",
        )
        session.add(row)
        await session.commit()
        await lock_execution_records(session, [row.service_id])
        await complete_stopped_runs(session, [row.service_id])
        await session.commit()
        await session.refresh(row)
        ended_at = row.ended_at
        assert ended_at is not None and row.status == expected
        assert row.error == "Retained diagnostic"
        await lock_execution_records(session, [row.service_id])
        await complete_stopped_runs(session, [row.service_id])
        await session.commit()
        await session.refresh(row)
        assert row.status == expected and row.ended_at == ended_at


@pytest.mark.asyncio
async def test_draft_metadata_and_graph_have_one_atomic_version(pipeline_database):
    async with pipeline_database() as session:
        library = PipelineLibrary(session)
        design, _ = await integration.published_design(session)
        changed = design.draft.model_copy(deep=True)
        changed.input_slots[0].label = "Updated input"
        saved = await library.save_draft(
            design.id,
            PipelineDraftSave(
                expected_version=2,
                definition=changed,
                name="Renamed",
                description="Together",
            ),
        )
        assert saved.version == 3
        assert (saved.name, saved.description) == ("Renamed", "Together")
        assert saved.draft == changed
        with pytest.raises(ValidationError, match="name"):
            await library.save_draft(
                design.id,
                PipelineDraftSave(
                    expected_version=3,
                    definition=design.draft,
                    name="   ",
                ),
            )
        await session.rollback()
        unchanged = await library.get(design.id)
        assert unchanged.version == 3 and unchanged.draft == changed
        with pytest.raises(ConflictError):
            await library.save_draft(
                design.id,
                PipelineDraftSave(
                    expected_version=2,
                    definition=design.draft,
                    name="Stale rename",
                ),
            )


@pytest.mark.asyncio
async def test_published_compatibility_uses_executable_contracts(
    pipeline_database, monkeypatch
):
    catalog = importlib.import_module("off_key_core.models.pipeline_catalog")
    compiler = importlib.import_module("off_key_core.models.pipeline_compiler")
    components = catalog.pipeline_components
    async with pipeline_database() as session:
        _, revision = await integration.published_design(session)

        def cosmetic_components():
            result = components()
            result[-1].description += " Clearer explanatory wording."
            return result

        monkeypatch.setattr(catalog, "pipeline_components", cosmetic_components)
        assert pipeline_catalog_id() != revision.catalog_id
        assert compile_pipeline(revision.definition).fingerprint == revision.fingerprint
        request = PipelineActivationRequest(
            revision_id=revision.id,
            bindings={"value": "current"},
            display_name="Stable executable",
            idempotency_key="compatible-catalog",
        )
        operation = await PipelineActivations(session).submit(request)
        assert operation.phase == "requested"

        def incompatible_components():
            result = components()
            next(
                item
                for item in result
                if item.id == revision.definition.nodes[0].component
            ).contract_version = 2
            return result

        monkeypatch.setattr(compiler, "pipeline_components", incompatible_components)
        with pytest.raises(ConflictError, match="contracts"):
            await PipelineActivations(session).submit(
                request.model_copy(
                    update={
                        "idempotency_key": "incompatible-catalog",
                    }
                )
            )


@pytest.mark.asyncio
async def test_maximum_revision_and_run_histories_are_paged_without_executable_copies(
    pipeline_database,
):
    definition = maximum_definition()
    statements = []
    engine = pipeline_database.kw["bind"]

    def record(_conn, _cursor, statement, *_args):
        statements.append(statement)

    async with pipeline_database() as session:
        library = PipelineLibrary(session)
        design = await library.create(
            PipelineCreate(name="Large history", definition=definition)
        )
        compiled = compile_pipeline(definition)
        now = datetime.now(UTC)
        for number in range(1, 106):
            session.add(
                PipelineRevision(
                    id=str(uuid4()),
                    pipeline_id=design.id,
                    number=number,
                    definition=compiled.definition.model_dump(mode="json"),
                    fingerprint=compiled.fingerprint,
                    catalog_id=pipeline_catalog_id(),
                    created_at=now,
                )
            )
        predecessor = None
        for index in range(105):
            row = PipelineRun(
                id=str(uuid4()),
                service_id=f"history-service-{index}",
                predecessor_run_id=predecessor,
                revision_id=None,
                execution=None,
                launch_config={},
                layout={},
                status="stopped",
                created_at=now,
                ended_at=now,
            )
            session.add(row)
            await session.flush()
            predecessor = row.id
        await session.commit()
        event.listen(engine.sync_engine, "before_cursor_execute", record)
        try:
            current = await library.get(design.id)
            assert len(current.revisions) == 25 and current.revision_next_before == 81
            assert len(current.model_dump_json().encode()) < 100_000
            assert all(not hasattr(item, "definition") for item in current.revisions)
            numbers = [item.number for item in current.revisions]
            before = current.revision_next_before
            while before is not None:
                page = await library.revisions(
                    design.id, PipelineRevisionQuery(before=before)
                )
                numbers.extend(item.number for item in page.items)
                before = page.next_before
            assert numbers == list(range(105, 0, -1))
            detail = await library.revision(design.id, current.revisions[-1].id)
            assert detail.definition == compiled.definition
            statements.clear()
            services = []
            service_id = "history-service-104"
            while service_id is not None:
                page = await library.history(service_id, PipelineHistoryQuery())
                assert len(page.items) <= 25
                assert len(page.model_dump_json().encode()) < 25_000
                assert all(not hasattr(item, "execution") for item in page.items)
                services.extend(item.service_id for item in page.items)
                service_id = page.next_service_id
            assert services == [
                f"history-service-{index}" for index in range(104, -1, -1)
            ]
            assert len(statements) == 5  # One recursive SELECT per page, never N+1.
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", record)


@pytest.mark.asyncio
async def test_library_search_and_pagination_select_only_summaries(pipeline_database):
    async with pipeline_database() as session:
        library = PipelineLibrary(session)
        definition = (
            integration.pipeline_catalog()
            .templates[0]
            .definition.model_dump(mode="json")
        )
        now = datetime.now(UTC)
        session.add_all(
            [
                MonitoringPipeline(
                    id=f"design-{index:03}",
                    name=f"Design {index:03}",
                    description="Searchable",
                    archived=False,
                    version=1,
                    draft=definition,
                    layout={},
                    created_at=now,
                    updated_at=now,
                )
                for index in range(105)
            ]
        )
        await session.commit()
        found = []
        offset = 0
        while offset is not None:
            page = await library.list(PipelineListQuery(offset=offset))
            assert len(page.items) <= 25
            assert all(not hasattr(item, "draft") for item in page.items)
            assert all(item.revision_count == 0 for item in page.items)
            found.extend(item.id for item in page.items)
            offset = page.next_offset
        assert len(found) == len(set(found)) == 105
        page = await library.list(PipelineListQuery(query="Design 104"))
        assert [item.id for item in page.items] == ["design-104"]
