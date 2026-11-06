"""Mark known problems on a Dojo dataset as time intervals.

Labels of one dataset never overlap. Writes lock the dataset row, so two
members labelling at once cannot slip overlapping intervals past the check.
"""

from datetime import datetime
from uuid import uuid4

from off_key_core.db.maintenance import require_application_writes
from off_key_core.db.models import DojoDataset, DojoLabel
from off_key_core.schemas.dojo import (
    MAX_DATASET_LABELS,
    LabelChange,
    LabelCreate,
    LabelList,
    LabelView,
)
from sqlalchemy import func, select

from ...domain import ConflictError, NotFoundError, ValidationError


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


class DojoLabels:
    def __init__(self, session):
        self.session = session

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
