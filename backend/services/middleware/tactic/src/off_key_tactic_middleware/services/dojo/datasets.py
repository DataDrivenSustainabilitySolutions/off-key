"""Create, read and delete Dojo datasets.

Points are copied in batches with PostgreSQL COPY inside one transaction, so a
rejected upload leaves nothing behind. Writes respect release maintenance but
do not take the collection lock: a long import must not block catalogue edits.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import uuid4

from asyncpg.exceptions import UniqueViolationError
from off_key_core.db.collection_runtime import read_collection_runtime
from off_key_core.db.maintenance import require_application_writes
from off_key_core.db.models import (
    DojoDataset,
    DojoPoint,
    DojoRun,
    DojoRunResult,
    DojoSeries,
    Telemetry,
)
from off_key_core.schemas.dojo import (
    MAX_DATASET_POINTS,
    MAX_DATASET_SERIES,
    CsvImportQuery,
    DatasetChange,
    DatasetFromHistory,
    DatasetListPage,
    DatasetListQuery,
    DatasetOrigin,
    DatasetPoint,
    DatasetPointsPage,
    DatasetPointsQuery,
    DatasetSeriesView,
    DatasetSummary,
    DatasetView,
)
from sqlalchemy import Text, delete, func, insert, literal, select, update

from ...domain import ConflictError, NotFoundError, ValidationError
from .csv_import import read_points

COPY_BATCH = 20_000
POINT_COLUMNS = ("series_id", "timestamp", "value")


@dataclass
class _Series:
    id: str
    position: int
    name: str
    unit: str | None = None
    reading_id: str | None = None
    point_count: int = 0
    start_at: datetime | None = None
    end_at: datetime | None = None
    stored: bool = False

    def add(self, timestamp: datetime) -> None:
        self.point_count += 1
        if self.start_at is None or timestamp < self.start_at:
            self.start_at = timestamp
        if self.end_at is None or timestamp > self.end_at:
            self.end_at = timestamp


def _too_many_points() -> ValidationError:
    return ValidationError(
        f"A dataset holds at most {MAX_DATASET_POINTS:,} points; "
        "upload a shorter window or fewer series"
    )


def _too_many_series() -> ValidationError:
    return ValidationError(f"A dataset holds at most {MAX_DATASET_SERIES} series")


def _unique_names(labels: Iterable[str]) -> list[str]:
    seen: dict[str, int] = {}
    names = []
    for label in labels:
        count = seen.get(label, 0) + 1
        seen[label] = count
        names.append(label if count == 1 else f"{label} ({count})")
    return names


class DojoDatasets:
    def __init__(self, session):
        self.session = session

    async def list(self, query: DatasetListQuery) -> DatasetListPage:
        series_count = (
            select(func.count())
            .where(DojoSeries.dataset_id == DojoDataset.id)
            .correlate(DojoDataset)
            .scalar_subquery()
        )
        rows = (
            await self.session.execute(
                select(DojoDataset, series_count)
                .order_by(DojoDataset.created_at.desc(), DojoDataset.id)
                .offset(query.offset)
                .limit(query.limit + 1)
            )
        ).all()
        items = [self._summary(row, count) for row, count in rows[: query.limit]]
        more = len(rows) > query.limit
        return DatasetListPage(
            items=items, next_offset=query.offset + query.limit if more else None
        )

    async def get(self, dataset_id: str) -> DatasetView:
        row = await self._row(dataset_id)
        series = (
            await self.session.scalars(
                select(DojoSeries)
                .where(DojoSeries.dataset_id == row.id)
                .order_by(DojoSeries.position)
            )
        ).all()
        return DatasetView(
            **self._summary(row, len(series)).model_dump(),
            source=row.source,
            series=[
                DatasetSeriesView.model_validate(
                    {key: getattr(item, key) for key in DatasetSeriesView.model_fields}
                )
                for item in series
            ],
        )

    async def change(self, dataset_id: str, change: DatasetChange) -> DatasetView:
        await require_application_writes(self.session)
        row = await self._row(dataset_id, lock=True)
        if change.name is not None:
            row.name = self._name(change.name)
        if change.description is not None:
            row.description = change.description
        await self.session.commit()
        return await self.get(dataset_id)

    async def remove(self, dataset_id: str) -> None:
        await require_application_writes(self.session)
        row = await self._row(dataset_id, lock=True)
        runs = select(DojoRun.id).where(DojoRun.dataset_id == row.id)
        active = await self.session.scalar(
            select(func.count()).where(
                DojoRun.dataset_id == row.id,
                DojoRun.status.in_(("queued", "running")),
            )
        )
        if active:
            raise ConflictError("Cancel the dataset's runs before deleting it")
        # Points and results carry no foreign key, so they go first; the
        # runs themselves cascade with the dataset.
        await self.session.execute(
            delete(DojoRunResult).where(DojoRunResult.run_id.in_(runs))
        )
        await self.session.execute(
            delete(DojoPoint).where(
                DojoPoint.series_id.in_(
                    select(DojoSeries.id).where(DojoSeries.dataset_id == row.id)
                )
            )
        )
        await self.session.delete(row)
        await self.session.commit()

    async def points(
        self, dataset_id: str, series_id: str, query: DatasetPointsQuery
    ) -> DatasetPointsPage:
        series = await self.session.get(DojoSeries, series_id)
        if series is None or series.dataset_id != dataset_id:
            raise NotFoundError("Series not found")
        statement = select(DojoPoint.timestamp, DojoPoint.value).where(
            DojoPoint.series_id == series_id
        )
        if query.after is not None:
            statement = statement.where(DojoPoint.timestamp > query.after)
        rows = (
            await self.session.execute(
                statement.order_by(DojoPoint.timestamp).limit(query.limit + 1)
            )
        ).all()
        items = [
            DatasetPoint(timestamp=timestamp, value=value)
            for timestamp, value in rows[: query.limit]
        ]
        return DatasetPointsPage(
            items=items,
            next_after=items[-1].timestamp if len(rows) > query.limit else None,
        )

    async def import_csv(
        self, body: bytes, query: CsvImportQuery, *, created_by: int | None
    ) -> DatasetView:
        await require_application_writes(self.session)
        declared, points = read_points(body, query)
        if len(declared) > MAX_DATASET_SERIES:
            raise _too_many_series()
        dataset = self._dataset(
            query.name,
            query.description,
            "csv",
            {
                "filename": query.filename,
                "layout": query.layout,
                "timestamp_column": query.timestamp_column,
            },
            created_by,
        )
        series = {
            name: _Series(id=str(uuid4()), position=position, name=name)
            for position, name in enumerate(declared)
        }
        total = 0
        batch: list[tuple[str, datetime, float]] = []
        for name, timestamp, value in points:
            item = series.get(name)
            if item is None:
                if len(series) >= MAX_DATASET_SERIES:
                    raise _too_many_series()
                item = series[name] = _Series(
                    id=str(uuid4()), position=len(series), name=name
                )
            item.add(timestamp)
            total += 1
            if total > MAX_DATASET_POINTS:
                raise _too_many_points()
            batch.append((item.id, timestamp, value))
            if len(batch) >= COPY_BATCH:
                await self._store_series(dataset.id, series.values())
                await self._copy(batch, series)
                batch = []
        if total == 0:
            raise ValidationError("The CSV contains no values")
        await self._store_series(dataset.id, series.values())
        await self._copy(batch, series)
        return await self._finish(dataset, series.values())

    async def import_history(
        self, request: DatasetFromHistory, *, created_by: int | None
    ) -> DatasetView:
        await require_application_writes(self.session)
        snapshot = await read_collection_runtime(self.session)
        streams = {
            stream.definition.id: stream
            for stream in snapshot.catalog.streams()
            if stream.value_type == "number"
        }
        missing = [item for item in request.reading_ids if item not in streams]
        if missing:
            raise ValidationError(
                f"Not numeric catalogue readings: {', '.join(missing[:5])}"
            )
        chosen = [streams[item] for item in request.reading_ids]
        window = (
            Telemetry.timestamp >= request.start,
            Telemetry.timestamp < request.end,
            Telemetry.value.is_not(None),
        )

        def recorded(stream):
            return (
                Telemetry.charger_id == stream.charger_id,
                Telemetry.type == stream.key,
                *window,
            )

        total = 0
        for stream in chosen:
            total += await self.session.scalar(
                select(func.count()).select_from(Telemetry).where(*recorded(stream))
            )
            if total > MAX_DATASET_POINTS:
                raise _too_many_points()
        if total == 0:
            raise ValidationError("The chosen readings recorded nothing in this window")
        dataset = self._dataset(
            request.name,
            request.description,
            "history",
            {
                "reading_ids": request.reading_ids,
                "start": request.start.isoformat(),
                "end": request.end.isoformat(),
            },
            created_by,
        )
        names = _unique_names(stream.definition.label for stream in chosen)
        series = [
            _Series(
                id=str(uuid4()),
                position=position,
                name=name,
                unit=stream.definition.unit,
                reading_id=stream.definition.id,
            )
            for position, (name, stream) in enumerate(zip(names, chosen, strict=True))
        ]
        await self._store_series(dataset.id, series)
        for item, stream in zip(series, chosen, strict=True):
            await self.session.execute(
                insert(DojoPoint).from_select(
                    list(POINT_COLUMNS),
                    select(
                        literal(item.id, Text),
                        Telemetry.timestamp,
                        Telemetry.value,
                    ).where(*recorded(stream)),
                )
            )
            count, start, end = (
                await self.session.execute(
                    select(
                        func.count(),
                        func.min(DojoPoint.timestamp),
                        func.max(DojoPoint.timestamp),
                    ).where(DojoPoint.series_id == item.id)
                )
            ).one()
            item.point_count, item.start_at, item.end_at = count, start, end
        return await self._finish(dataset, series)

    def _dataset(self, name, description, origin, source, created_by):
        dataset = DojoDataset(
            id=str(uuid4()),
            name=self._name(name),
            description=description,
            origin=origin,
            source=source,
            created_by=created_by,
            point_count=0,
        )
        self.session.add(dataset)
        return dataset

    async def _store_series(self, dataset_id: str, series: Iterable[_Series]) -> None:
        new = [item for item in series if not item.stored]
        if not new:
            return
        await self.session.flush()
        await self.session.execute(
            insert(DojoSeries),
            [
                {
                    "id": item.id,
                    "dataset_id": dataset_id,
                    "position": item.position,
                    "name": item.name,
                    "unit": item.unit,
                    "reading_id": item.reading_id,
                    "point_count": 0,
                }
                for item in new
            ],
        )
        for item in new:
            item.stored = True

    async def _copy(self, batch, series) -> None:
        if not batch:
            return
        connection = await self.session.connection()
        raw = await connection.get_raw_connection()
        try:
            await raw.driver_connection.copy_records_to_table(
                DojoPoint.__tablename__, records=batch, columns=POINT_COLUMNS
            )
        except UniqueViolationError:
            names = {item.id: item.name for item in series.values()}
            raise ValidationError(
                "A series has two values for the same timestamp"
                + (f" ({names[batch[0][0]]!r} or another)" if batch else "")
            ) from None

    async def _finish(self, dataset, series: Iterable[_Series]) -> DatasetView:
        series = list(series)
        for item in series:
            await self.session.execute(
                update(DojoSeries)
                .where(DojoSeries.id == item.id)
                .values(
                    point_count=item.point_count,
                    start_at=item.start_at,
                    end_at=item.end_at,
                )
            )
        # Series a wide CSV declared but never filled are not worth keeping.
        await self.session.execute(
            delete(DojoSeries).where(
                DojoSeries.dataset_id == dataset.id, DojoSeries.point_count == 0
            )
        )
        filled = [item for item in series if item.point_count]
        dataset.point_count = sum(item.point_count for item in filled)
        dataset.start_at = min(
            (item.start_at for item in filled if item.start_at), default=None
        )
        dataset.end_at = max(
            (item.end_at for item in filled if item.end_at), default=None
        )
        await self.session.commit()
        return await self.get(dataset.id)

    async def _row(self, dataset_id: str, *, lock: bool = False) -> DojoDataset:
        row = await self.session.get(
            DojoDataset, dataset_id, with_for_update=lock, populate_existing=True
        )
        if row is None:
            raise NotFoundError("Dataset not found")
        return row

    @staticmethod
    def _name(value: str) -> str:
        name = value.strip()
        if not name:
            raise ValidationError("Dataset name must not be empty")
        return name

    @staticmethod
    def _summary(row: DojoDataset, series_count: int) -> DatasetSummary:
        return DatasetSummary(
            id=row.id,
            name=row.name,
            description=row.description,
            origin=cast(DatasetOrigin, row.origin),
            point_count=row.point_count,
            series_count=series_count,
            start_at=row.start_at,
            end_at=row.end_at,
            created_by=row.created_by,
            created_at=row.created_at,
        )
