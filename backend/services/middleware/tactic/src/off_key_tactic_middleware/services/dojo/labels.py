"""Mark known problems on a Dojo dataset as time intervals.

Labels of one dataset never overlap. Writes lock the dataset row, so two
members labelling at once cannot slip overlapping intervals past the check.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import uuid4

from off_key_core.db.collection_runtime import read_collection_runtime
from off_key_core.db.maintenance import require_application_writes
from off_key_core.db.models import DojoDataset, DojoLabel, DojoSeries
from off_key_core.schemas.alarms import MULTIVARIATE_TELEMETRY_TYPE
from off_key_core.schemas.dojo import (
    MAX_DATASET_LABELS,
    MAX_LABEL_SUGGESTIONS,
    MAX_SUGGESTION_ALARMS,
    LabelChange,
    LabelCreate,
    LabelList,
    LabelSuggestion,
    LabelSuggestionList,
    LabelSuggestionQuery,
    LabelView,
)
from sqlalchemy import func, select

from ...domain import ConflictError, NotFoundError, ValidationError
from ...repositories import AnomalyRepository
from ...repositories.anomaly_filters import AnomalyFilters
from ..data.alarm_catalogue import reading_scope

# A label needs an end after its start; a lone alarm gets this much.
LONE_ALARM = timedelta(seconds=1)


def label_view(row: DojoLabel) -> LabelView:
    return LabelView(
        id=row.id,
        dataset_id=row.dataset_id,
        start_at=row.start_at,
        end_at=row.end_at,
        note=row.note,
        created_by=row.created_by,
        created_at=row.created_at,
    )


async def dataset_labels(session, dataset_id: str) -> list[DojoLabel]:
    return list(
        (
            await session.scalars(
                select(DojoLabel)
                .where(DojoLabel.dataset_id == dataset_id)
                .order_by(DojoLabel.start_at, DojoLabel.id)
            )
        ).all()
    )


@dataclass
class _Episode:
    start: datetime
    end: datetime
    count: int = 0
    monitors: dict[str, None] = field(default_factory=dict)
    readings: dict[str, None] = field(default_factory=dict)

    def suggestion(self, order: list[str]) -> LabelSuggestion:
        return LabelSuggestion(
            start_at=self.start,
            end_at=max(self.end, self.start + LONE_ALARM),
            alarm_count=self.count,
            monitor_ids=[item for item in self.monitors if item],
            reading_ids=[item for item in order if item in self.readings],
        )


class DojoLabels:
    def __init__(self, session):
        self.session = session

    async def suggestions(
        self, dataset_id: str, query: LabelSuggestionQuery
    ) -> LabelSuggestionList:
        """Alarms live monitors recorded on the dataset's readings, as episodes.

        Only series copied from recorded readings have a reading to look up,
        and only while the catalogue still collects it; an upload has none.
        """
        dataset = await self._dataset(dataset_id)
        none = LabelSuggestionList(items=[], truncated=False)
        reading_ids = list(
            (
                await self.session.scalars(
                    select(DojoSeries.reading_id)
                    .where(
                        DojoSeries.dataset_id == dataset.id,
                        DojoSeries.reading_id.is_not(None),
                    )
                    .order_by(DojoSeries.position)
                )
            ).all()
        )
        if not reading_ids or dataset.start_at is None or dataset.end_at is None:
            return none
        bindings = {
            reading_id: binding.model_dump()
            for reading_id, binding in (
                await read_collection_runtime(self.session)
            ).catalog.bindings.items()
        }
        scope, _ = reading_scope(bindings, reading_ids)
        if not scope.pairs:
            return none
        rows = await AnomalyRepository(self.session).timeline(
            AnomalyFilters(
                scope=scope,
                since=dataset.start_at,
                # The dataset's last value is inside its span.
                until=dataset.end_at + timedelta(microseconds=1),
            ),
            limit=MAX_SUGGESTION_ALARMS + 1,
        )
        truncated = len(rows) > MAX_SUGGESTION_ALARMS
        recorded = {
            (bindings[item]["entity_id"], bindings[item]["telemetry_key"]): item
            for item in reading_ids
            if item in bindings
        }
        gap = timedelta(seconds=query.gap_seconds)
        episodes: list[_Episode] = []
        for timestamp, monitor, entity, key, sensor_set in rows[:MAX_SUGGESTION_ALARMS]:
            if not episodes or timestamp - episodes[-1].end > gap:
                if len(episodes) == MAX_LABEL_SUGGESTIONS:
                    truncated = True
                    break
                episodes.append(_Episode(start=timestamp, end=timestamp))
            episode = episodes[-1]
            episode.end = timestamp
            episode.count += 1
            episode.monitors[monitor] = None
            keys = sensor_set if isinstance(sensor_set, list) and sensor_set else None
            for (owner, recorded_key), reading_id in recorded.items():
                if owner == entity and (
                    recorded_key in keys
                    if keys
                    else key in (recorded_key, MULTIVARIATE_TELEMETRY_TYPE)
                ):
                    episode.readings[reading_id] = None
        return LabelSuggestionList(
            items=[item.suggestion(reading_ids) for item in episodes],
            truncated=truncated,
        )

    async def list(self, dataset_id: str) -> LabelList:
        await self._dataset(dataset_id)
        rows = await dataset_labels(self.session, dataset_id)
        return LabelList(items=[label_view(row) for row in rows])

    async def create(
        self, dataset_id: str, request: LabelCreate, *, created_by: int | None
    ) -> LabelView:
        await require_application_writes(self.session)
        dataset = await self._dataset(dataset_id, lock=True)
        count = await self.session.scalar(
            select(func.count()).where(DojoLabel.dataset_id == dataset.id)
        )
        if count >= MAX_DATASET_LABELS:
            raise ConflictError(f"A dataset holds at most {MAX_DATASET_LABELS} labels")
        await self._check(dataset, request.start_at, request.end_at, None)
        row = DojoLabel(
            id=str(uuid4()),
            dataset_id=dataset.id,
            start_at=request.start_at,
            end_at=request.end_at,
            note=request.note.strip(),
            created_by=created_by,
        )
        self.session.add(row)
        await self.session.commit()
        return label_view(await self._row(dataset_id, row.id))

    async def change(
        self, dataset_id: str, label_id: str, change: LabelChange
    ) -> LabelView:
        await require_application_writes(self.session)
        dataset = await self._dataset(dataset_id, lock=True)
        row = await self._row(dataset_id, label_id)
        start_at = change.start_at or row.start_at
        end_at = change.end_at or row.end_at
        if end_at <= start_at:
            raise ValidationError("end_at must be after start_at")
        await self._check(dataset, start_at, end_at, row.id)
        row.start_at = start_at
        row.end_at = end_at
        if change.note is not None:
            row.note = change.note.strip()
        await self.session.commit()
        return label_view(await self._row(dataset_id, label_id))

    async def remove(self, dataset_id: str, label_id: str) -> None:
        await require_application_writes(self.session)
        await self._dataset(dataset_id, lock=True)
        row = await self._row(dataset_id, label_id)
        await self.session.delete(row)
        await self.session.commit()

    async def _check(
        self,
        dataset: DojoDataset,
        start_at: datetime,
        end_at: datetime,
        label_id: str | None,
    ) -> None:
        if (
            dataset.start_at is not None
            and dataset.end_at is not None
            and (end_at < dataset.start_at or start_at > dataset.end_at)
        ):
            raise ValidationError(
                "The label lies outside the dataset, which spans "
                f"{dataset.start_at.isoformat()} to {dataset.end_at.isoformat()}"
            )
        statement = select(DojoLabel).where(
            DojoLabel.dataset_id == dataset.id,
            DojoLabel.start_at < end_at,
            DojoLabel.end_at > start_at,
        )
        if label_id is not None:
            statement = statement.where(DojoLabel.id != label_id)
        other = (
            await self.session.scalars(statement.order_by(DojoLabel.start_at))
        ).first()
        if other is not None:
            raise ConflictError(
                "Labels may not overlap; the label from "
                f"{other.start_at.isoformat()} to {other.end_at.isoformat()} "
                "already covers part of this interval"
            )

    async def _dataset(self, dataset_id: str, *, lock: bool = False) -> DojoDataset:
        row = await self.session.get(
            DojoDataset, dataset_id, with_for_update=lock, populate_existing=True
        )
        if row is None:
            raise NotFoundError("Dataset not found")
        return row

    async def _row(self, dataset_id: str, label_id: str) -> DojoLabel:
        row = await self.session.get(DojoLabel, label_id, populate_existing=True)
        if row is None or row.dataset_id != dataset_id:
            raise NotFoundError("Label not found")
        return row
