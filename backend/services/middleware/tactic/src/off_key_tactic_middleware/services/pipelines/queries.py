"""Bounded read projections; list and history queries never load executables."""

from off_key_core.db.models import MonitoringPipeline, PipelineRevision, PipelineRun
from off_key_core.schemas.pipelines import (
    PipelineHistoryPage,
    PipelineHistoryQuery,
    PipelineListPage,
    PipelineListQuery,
    PipelineRevisionPage,
    PipelineRevisionQuery,
    PipelineRevisionSummary,
    PipelineRunSummary,
    PipelineSummary,
)
from sqlalchemy import String, any_, cast, func, literal, or_, select
from sqlalchemy.dialects.postgresql import ARRAY, array
from sqlalchemy.orm import aliased


async def list_designs(session, query: PipelineListQuery) -> PipelineListPage:
    revision_count = (
        select(func.count(PipelineRevision.id))
        .where(PipelineRevision.pipeline_id == MonitoringPipeline.id)
        .correlate(MonitoringPipeline)
        .scalar_subquery()
    )
    fields = [
        getattr(MonitoringPipeline, name)
        for name in PipelineSummary.model_fields
        if name not in {"strategy", "revision_count"}
    ]
    statement = select(
        *fields,
        func.coalesce(
            MonitoringPipeline.draft["strategy"].as_string(), "static_baseline"
        ).label("strategy"),
        revision_count.label("revision_count"),
    ).where(
        MonitoringPipeline.archived == query.archived,
        MonitoringPipeline.is_template.is_(True),
    )
    if query.query:
        statement = statement.where(
            or_(
                func.lower(MonitoringPipeline.name).contains(
                    query.query.lower(), autoescape=True
                ),
                func.lower(MonitoringPipeline.description).contains(
                    query.query.lower(), autoescape=True
                ),
            )
        )
    rows = (
        (
            await session.execute(
                statement.order_by(
                    MonitoringPipeline.updated_at.desc(), MonitoringPipeline.id.desc()
                )
                .offset(query.offset)
                .limit(query.limit + 1)
            )
        )
        .mappings()
        .all()
    )
    return PipelineListPage(
        items=[PipelineSummary.model_validate(row) for row in rows[: query.limit]],
        next_offset=query.offset + query.limit if len(rows) > query.limit else None,
    )


async def list_revisions(session, pipeline_id, query: PipelineRevisionQuery):
    statement = select(
        *[
            getattr(PipelineRevision, name)
            for name in PipelineRevisionSummary.model_fields
        ]
    ).where(PipelineRevision.pipeline_id == pipeline_id)
    if query.before is not None:
        statement = statement.where(PipelineRevision.number < query.before)
    rows = (
        (
            await session.execute(
                statement.order_by(PipelineRevision.number.desc()).limit(
                    query.limit + 1
                )
            )
        )
        .mappings()
        .all()
    )
    return PipelineRevisionPage(
        items=[
            PipelineRevisionSummary.model_validate(row) for row in rows[: query.limit]
        ],
        next_before=rows[query.limit - 1]["number"]
        if len(rows) > query.limit
        else None,
    )


async def run_history(session, service_id, query: PipelineHistoryQuery):
    fields = tuple(PipelineRunSummary.model_fields)
    history = (
        select(
            *[getattr(PipelineRun, name) for name in fields],
            literal(1).label("depth"),
            cast(array([PipelineRun.id]), ARRAY(String)).label("visited"),
        )
        .where(PipelineRun.service_id == service_id)
        .cte("run_history", recursive=True)
    )
    parent = aliased(PipelineRun)
    history = history.union_all(
        select(
            *[getattr(parent, name) for name in fields],
            (history.c.depth + 1).label("depth"),
            (history.c.visited + array([parent.id])).label("visited"),
        )
        .join(history, parent.id == history.c.predecessor_run_id)
        .where(
            history.c.depth <= query.limit,
            ~(parent.id == any_(history.c.visited)),
        )
    )
    rows = (
        (
            await session.execute(
                select(*[getattr(history.c, name) for name in fields])
                .order_by(history.c.depth)
                .limit(query.limit + 1)
            )
        )
        .mappings()
        .all()
    )
    return PipelineHistoryPage(
        items=[PipelineRunSummary.model_validate(row) for row in rows[: query.limit]],
        next_service_id=rows[query.limit]["service_id"]
        if len(rows) > query.limit
        else None,
    )
