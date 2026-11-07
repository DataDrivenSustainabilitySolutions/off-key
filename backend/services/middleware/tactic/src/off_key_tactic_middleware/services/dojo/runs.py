"""Queue, read, cancel and delete Dojo runs.

TACTIC compiles and binds the design when a run is created, so a run that is
accepted can only fail on what the data does to the model. The Dojo worker
on the RADAR image claims queued runs and executes them.
"""

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from off_key_core.db.locks import DOJO_QUEUE_LOCK
from off_key_core.db.maintenance import require_application_writes
from off_key_core.db.models import DojoDataset, DojoRun, DojoRunResult, DojoSeries
from off_key_core.models.dojo_runs import BoundSeries, bind_dataset
from off_key_core.models.pipelines import compile_pipeline
from off_key_core.schemas.dojo import (
    MAX_ACTIVE_RUNS,
    PromotedBinding,
    RunAlignment,
    RunBinding,
    RunCreate,
    RunListPage,
    RunListQuery,
    RunPromote,
    RunPromotion,
    RunResult,
    RunResultsPage,
    RunResultsQuery,
    RunStatus,
    RunSummary,
    RunView,
)
from off_key_core.schemas.pipelines import PipelineCreate, PipelineDefinition
from off_key_core.utils.json_budget import bounded_utf8_text
from sqlalchemy import delete, func, select, text

from ...domain import ConflictError, NotFoundError, ValidationError
from ..pipelines.library import PipelineLibrary

ACTIVE = ("queued", "running")


class DojoRuns:
    def __init__(self, session):
        self.session = session

    async def create(self, request: RunCreate, *, created_by: int | None) -> RunView:
        await require_application_writes(self.session)
        dataset = await self.session.get(DojoDataset, request.dataset_id)
        if dataset is None:
            raise NotFoundError("Dataset not found")
        try:
            compiled = compile_pipeline(request.definition)
        except ValueError as exc:
            raise ValidationError(bounded_utf8_text(str(exc), 4096)) from exc
        series = {
            item.id: item
            for item in (
                await self.session.scalars(
                    select(DojoSeries).where(DojoSeries.dataset_id == dataset.id)
                )
            ).all()
        }
        unknown = sorted(set(request.bindings.values()) - series.keys())
        if unknown:
            raise ValidationError(
                f"The dataset has no series {', '.join(map(repr, unknown))}"
            )
        run_id = str(uuid4())
        try:
            execution = bind_dataset(
                compiled.definition,
                {
                    slot: BoundSeries(
                        id=item.id,
                        position=item.position,
                        name=item.name,
                        unit=item.unit,
                    )
                    for slot, item in (
                        (slot, series[series_id])
                        for slot, series_id in request.bindings.items()
                    )
                },
                run_id=run_id,
            )
        except ValueError as exc:
            raise ValidationError(bounded_utf8_text(str(exc), 4096)) from exc
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": DOJO_QUEUE_LOCK}
        )
        active = await self.session.scalar(
            select(func.count()).where(DojoRun.status.in_(ACTIVE))
        )
        if active >= MAX_ACTIVE_RUNS:
            raise ConflictError(
                f"At most {MAX_ACTIVE_RUNS} runs can wait or run at once; "
                "wait for one to finish or cancel one"
            )
        bound = [series[request.bindings[item.slot_id]] for item in execution.bindings]
        row = DojoRun(
            id=run_id,
            dataset_id=dataset.id,
            name=request.name.strip(),
            status="queued",
            config={
                "execution": execution.model_dump(mode="json"),
                "alignment": request.alignment.model_dump(mode="json"),
                "series": [
                    {
                        "id": item.id,
                        "topic": binding.accepted_topic,
                        "slot_id": binding.slot_id,
                        "name": item.name,
                    }
                    for item, binding in zip(bound, execution.bindings, strict=True)
                ],
            },
            cancel_requested=False,
            points_total=sum(item.point_count for item in bound),
            points_read=0,
            result_count=0,
            alarm_count=0,
            stats={},
            created_by=created_by,
        )
        self.session.add(row)
        await self.session.commit()
        return await self.get(run_id)

    async def list(self, query: RunListQuery) -> RunListPage:
        statement = select(DojoRun)
        if query.dataset_id is not None:
            statement = statement.where(DojoRun.dataset_id == query.dataset_id)
        if query.status is not None:
            statement = statement.where(DojoRun.status == query.status)
        rows = (
            await self.session.scalars(
                statement.order_by(DojoRun.created_at.desc(), DojoRun.id)
                .offset(query.offset)
                .limit(query.limit + 1)
            )
        ).all()
        more = len(rows) > query.limit
        return RunListPage(
            items=[self._summary(row) for row in rows[: query.limit]],
            next_offset=query.offset + query.limit if more else None,
        )

    async def get(self, run_id: str) -> RunView:
        row = await self._row(run_id)
        config = row.config
        return RunView(
            **self._summary(row).model_dump(),
            definition=config["execution"]["definition"],
            bindings=[
                RunBinding(
                    slot_id=item["slot_id"],
                    series_id=item["id"],
                    series_name=item["name"],
                )
                for item in config["series"]
            ],
            alignment=RunAlignment.model_validate(config["alignment"]),
            cancel_requested=row.cancel_requested,
            stats=row.stats or {},
        )

    async def cancel(self, run_id: str) -> RunView:
        """A queued run ends at once; a running one at the worker's next beat."""
        await require_application_writes(self.session)
        row = await self._row(run_id, lock=True)
        if row.status == "queued":
            row.status = "cancelled"
            row.finished_at = datetime.now(UTC)
        elif row.status == "running":
            row.cancel_requested = True
        else:
            raise ConflictError(f"The run has already {row.status}")
        await self.session.commit()
        return await self.get(run_id)

    async def remove(self, run_id: str) -> None:
        await require_application_writes(self.session)
        row = await self._row(run_id, lock=True)
        if row.status in ACTIVE:
            raise ConflictError("Cancel the run before deleting it")
        # Results carry no foreign key (see DojoRunResult).
        await self.session.execute(
            delete(DojoRunResult).where(DojoRunResult.run_id == row.id)
        )
        await self.session.delete(row)
        await self.session.commit()

    async def promote(self, run_id: str, request: RunPromote) -> RunPromotion:
        """Save the run's compiled design as a library template.

        Each slot comes back with the series it was bound to and, for a series
        copied from recorded history, that series' catalogue reading, so the
        monitor can start on the inputs the design was tested on.
        """
        row = await self._row(run_id)
        definition = PipelineDefinition.model_validate(
            row.config["execution"]["definition"]
        )
        bound = row.config["series"]
        readings = dict(
            (
                await self.session.execute(
                    select(DojoSeries.id, DojoSeries.reading_id).where(
                        DojoSeries.id.in_([item["id"] for item in bound])
                    )
                )
            ).all()
        )
        labels = {slot.id: slot.label for slot in definition.input_slots}
        pipeline = await PipelineLibrary(self.session).create(
            PipelineCreate(
                name=request.name,
                description=request.description,
                definition=definition,
            )
        )
        return RunPromotion(
            pipeline_id=pipeline.id,
            pipeline_name=pipeline.name,
            bindings=[
                PromotedBinding(
                    slot_id=item["slot_id"],
                    slot_label=labels.get(item["slot_id"], item["slot_id"]),
                    series_name=item["name"],
                    reading_id=readings.get(item["id"]),
                )
                for item in bound
            ],
        )

    async def results(self, run_id: str, query: RunResultsQuery) -> RunResultsPage:
        await self._row(run_id)
        statement = select(DojoRunResult).where(DojoRunResult.run_id == run_id)
        if query.after is not None:
            statement = statement.where(DojoRunResult.sequence > query.after)
        if query.alarm is not None:
            statement = statement.where(DojoRunResult.alarm.is_(query.alarm))
        rows = (
            await self.session.scalars(
                statement.order_by(DojoRunResult.sequence).limit(query.limit + 1)
            )
        ).all()
        items = [
            RunResult(
                sequence=row.sequence,
                timestamp=row.timestamp,
                phase=row.phase,
                score=row.score,
                threshold=row.threshold,
                alarm=row.alarm,
            )
            for row in rows[: query.limit]
        ]
        return RunResultsPage(
            items=items,
            next_after=items[-1].sequence if len(rows) > query.limit else None,
        )

    async def _row(self, run_id: str, *, lock: bool = False) -> DojoRun:
        row = await self.session.get(
            DojoRun, run_id, with_for_update=lock, populate_existing=True
        )
        if row is None:
            raise NotFoundError("Run not found")
        return row

    @staticmethod
    def _summary(row: DojoRun) -> RunSummary:
        return RunSummary(
            id=row.id,
            dataset_id=row.dataset_id,
            name=row.name,
            status=cast(RunStatus, row.status),
            strategy=row.config["execution"]["definition"]["strategy"],
            points_total=row.points_total,
            points_read=row.points_read,
            result_count=row.result_count,
            alarm_count=row.alarm_count,
            error=row.error,
            created_by=row.created_by,
            created_at=row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )
