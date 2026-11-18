"""Create, read and delete Dojo datasets.

Points are copied in batches with PostgreSQL COPY inside one transaction, so a
rejected upload leaves nothing behind. Writes respect release maintenance but
do not take the collection lock: a long import must not block catalogue edits.
"""

import builtins
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import uuid4

from asyncpg.exceptions import UniqueViolationError
from off_key_core.config.logs import log_security_event
from off_key_core.db.collection_runtime import read_collection_runtime
from off_key_core.db.maintenance import require_application_writes
from off_key_core.db.models import (
    Agent,
    DojoDataset,
    DojoLabel,
    DojoPoint,
    DojoRun,
    DojoRunResult,
    DojoSeries,
    DojoSuite,
    DojoSuiteDataset,
    Telemetry,
    User,
)
from off_key_core.models.autocorrelation import profile_series
from off_key_core.schemas.dojo import (
    MAX_DATASET_LABELS,
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
    DatasetWithFaults,
    SeriesProfile,
)
from sqlalchemy import Text, delete, func, insert, literal, select, update

from ...domain import ConflictError, ForbiddenError, NotFoundError, ValidationError
from .csv_import import LabelRuns, read_points
from .faults import kept, plan_faults, written_value
from .labels import dataset_labels
from .owners import made_by, require_no_evidence

COPY_BATCH = 20_000
# Values a series profile reads, from the start of the series.
PROFILE_POINTS = 200_000
POINT_COLUMNS = ("series_id", "timestamp", "value")
# A label needs an end after its start; one marked value gets this much.
SINGLE_VALUE = timedelta(milliseconds=1)


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
        "use a shorter window or fewer series"
    )


def _too_many_series() -> ValidationError:
    return ValidationError(f"A dataset holds at most {MAX_DATASET_SERIES} series")


def _unique_names(labels: Iterable[str]) -> list[str]:
    labels = list(labels)
    reserved = set(labels)
    used: set[str] = set()
    suffixes: dict[str, int] = {}
    names = []
    for label in labels:
        name = label
        if name in used:
            suffix = suffixes.get(label, 2)
            while f"{label} ({suffix})" in reserved or f"{label} ({suffix})" in used:
                suffix += 1
            name = f"{label} ({suffix})"
            suffixes[label] = suffix + 1
        used.add(name)
        names.append(name)
    return names


class DojoDatasets:
    def __init__(self, session):
        self.session = session

    async def list(
        self, query: DatasetListQuery, caller: User | Agent | None = None
    ) -> DatasetListPage:
        series_count = (
            select(func.count())
            .where(DojoSeries.dataset_id == DojoDataset.id)
            .correlate(DojoDataset)
            .scalar_subquery()
        )
        statement = select(DojoDataset, series_count)
        if query.mine and caller is not None:
            statement = statement.where(
                made_by(caller, DojoDataset.created_by, DojoDataset.created_by_agent_id)
            )
        rows = (
            await self.session.execute(
                statement.order_by(DojoDataset.created_at.desc(), DojoDataset.id)
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

    async def remove(self, dataset_id: str, caller: User | Agent | None = None) -> None:
        """Delete a dataset with its runs. A key deletes only a dataset it made,
        holding only runs it queued, none of them a proposal's or monitor's test.
        """
        await require_application_writes(self.session)
        row = await self._row(dataset_id, lock=True)
        agent = caller if isinstance(caller, Agent) else None
        if agent is not None:
            await self._require_agent_may_delete(row, agent)
        runs = select(DojoRun.id).where(DojoRun.dataset_id == row.id)
        active = await self.session.scalar(
            select(func.count()).where(
                DojoRun.dataset_id == row.id,
                DojoRun.status.in_(("queued", "running")),
            )
        )
        if active:
            raise ConflictError("Cancel the dataset's runs before deleting it")
        suites = (
            await self.session.scalars(
                select(DojoSuite.name)
                .join(DojoSuiteDataset, DojoSuiteDataset.suite_id == DojoSuite.id)
                .where(DojoSuiteDataset.dataset_id == row.id)
                .order_by(DojoSuite.name)
            )
        ).all()
        if suites:
            # A suite's datasets never change, so its studies stay comparable.
            raise ConflictError(
                "The dataset belongs to the benchmark suite "
                f"{', '.join(map(repr, suites[:3]))}; delete the suite first"
            )
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
        if agent is not None:
            log_security_event(
                "dojo_dataset_deleted_by_agent", agent.name, {"dataset_id": dataset_id}
            )

    async def _require_agent_may_delete(self, row: DojoDataset, agent: Agent) -> None:
        if row.created_by_agent_id != agent.id:
            raise ForbiddenError("A key deletes only the datasets it made")
        run_ids = list(
            await self.session.scalars(
                select(DojoRun.id).where(DojoRun.dataset_id == row.id)
            )
        )
        others = await self.session.scalar(
            select(func.count()).where(
                DojoRun.dataset_id == row.id,
                DojoRun.created_by_agent_id.is_distinct_from(agent.id),
            )
        )
        if others:
            raise ForbiddenError(
                "The dataset holds runs that a member or another key queued, "
                "so a key cannot delete it"
            )
        await require_no_evidence(self.session, run_ids)

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

    async def profile(self, dataset_id: str, series_id: str) -> SeriesProfile:
        """How a series relates to its own past, from its first values."""
        series = await self.session.get(DojoSeries, series_id)
        if series is None or series.dataset_id != dataset_id:
            raise NotFoundError("Series not found")
        total = await self.session.scalar(
            select(func.count()).where(DojoPoint.series_id == series_id)
        )
        rows = (
            await self.session.execute(
                select(DojoPoint.timestamp, DojoPoint.value)
                .where(DojoPoint.series_id == series_id)
                .order_by(DojoPoint.timestamp)
                .limit(PROFILE_POINTS)
            )
        ).all()
        return profile_series(
            series_id,
            series.name,
            [(timestamp, value) for timestamp, value in rows],
            total=int(total or 0),
        )

    async def import_csv(
        self,
        body: bytes,
        query: CsvImportQuery,
        *,
        created_by: int | None,
        created_by_agent: Agent | None = None,
    ) -> DatasetView:
        await require_application_writes(self.session)
        labels = LabelRuns() if query.label_column else None
        declared, points = read_points(body, query, labels)
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
                **({"label_column": query.label_column} if labels else {}),
            },
            created_by,
            created_by_agent,
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
        if labels is not None:
            self.add_labels(
                dataset.id,
                labels.intervals,
                f"Marked in {query.label_column!r} of the file",
                created_by,
            )
        return await self._finish(dataset, series.values())

    async def import_values(
        self,
        name: str,
        description: str,
        origin: str,
        source: dict,
        series: dict[str, builtins.list[tuple[datetime, float]]],
        *,
        created_by: int | None,
        created_by_agent: Agent | None = None,
        labels: Iterable[tuple[datetime, datetime]] = (),
        label_note: str = "",
    ) -> DatasetView:
        """Store series held in memory as a new dataset, with labels, at once."""
        await require_application_writes(self.session)
        if len(series) > MAX_DATASET_SERIES:
            raise _too_many_series()
        if sum(len(values) for values in series.values()) > MAX_DATASET_POINTS:
            raise _too_many_points()
        dataset = self._dataset(
            name, description, origin, source, created_by, created_by_agent
        )
        items = {
            label: _Series(id=str(uuid4()), position=position, name=label)
            for position, label in enumerate(series)
        }
        await self._store_series(dataset.id, items.values())
        for label, values in series.items():
            item = items[label]
            for start in range(0, len(values), COPY_BATCH):
                chunk = values[start : start + COPY_BATCH]
                for timestamp, _ in chunk:
                    item.add(timestamp)
                await self._copy(
                    [(item.id, timestamp, value) for timestamp, value in chunk], items
                )
        self.add_labels(dataset.id, labels, label_note, created_by)
        return await self._finish(dataset, items.values())

    def add_labels(
        self,
        dataset_id: str,
        intervals: Iterable[tuple[datetime, datetime]],
        note: str,
        created_by: int | None,
    ) -> None:
        """Labels that come with new values, in the transaction that stores them.

        They come from one ordered source, so they cannot overlap. A label of
        a single value lasts a millisecond, since a label must end after it
        starts.
        """
        intervals = list(intervals)
        if len(intervals) > MAX_DATASET_LABELS:
            raise ValidationError(
                f"The file marks {len(intervals)} anomalies; a dataset holds at "
                f"most {MAX_DATASET_LABELS} labels"
            )
        for start_at, end_at in intervals:
            self.session.add(
                DojoLabel(
                    id=str(uuid4()),
                    dataset_id=dataset_id,
                    start_at=start_at,
                    end_at=max(end_at, start_at + SINGLE_VALUE),
                    note=note,
                    created_by=created_by,
                )
            )

    async def import_history(
        self,
        request: DatasetFromHistory,
        *,
        created_by: int | None,
        created_by_agent: Agent | None = None,
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
        # Without a start, everything retention has kept so far is copied.
        window = (
            *(() if request.start is None else (Telemetry.timestamp >= request.start,)),
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
                "start": request.start.isoformat() if request.start else None,
                "end": request.end.isoformat(),
            },
            created_by,
            created_by_agent,
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
        copied = 0
        for item, stream in zip(series, chosen, strict=True):
            await self.session.execute(
                insert(DojoPoint).from_select(
                    list(POINT_COLUMNS),
                    select(
                        literal(item.id, Text),
                        Telemetry.timestamp,
                        Telemetry.value,
                    )
                    .where(*recorded(stream))
                    .limit(MAX_DATASET_POINTS - copied + 1),
                )
            )
            await self._measure(item)
            copied += item.point_count
            if copied > MAX_DATASET_POINTS:
                raise _too_many_points()
        return await self._finish(dataset, series)

    async def inject_faults(
        self,
        dataset_id: str,
        request: DatasetWithFaults,
        *,
        created_by: int | None,
        created_by_agent: Agent | None = None,
    ) -> DatasetView:
        """Copy a dataset with faults written in, each one a new label.

        The copy keeps the source's labels and readings, so a run on it is
        scored on every known problem, injected or not.
        """
        await require_application_writes(self.session)
        source = await self._row(dataset_id)
        originals = list(
            (
                await self.session.scalars(
                    select(DojoSeries)
                    .where(DojoSeries.dataset_id == source.id)
                    .order_by(DojoSeries.position)
                )
            ).all()
        )
        labels = await dataset_labels(self.session, source.id)
        planned = await plan_faults(
            self.session,
            request.faults,
            {item.id: item for item in originals},
            labels,
        )
        copies = {
            item.id: _Series(
                id=str(uuid4()),
                position=item.position,
                name=item.name,
                unit=item.unit,
                reading_id=item.reading_id,
            )
            for item in originals
        }
        faults = [
            {
                **item.fault.model_dump(mode="json"),
                "series_id": copies[item.series.id].id,
                "size": item.size,
            }
            for item in planned
        ]
        dataset = self._dataset(
            request.name,
            request.description,
            source.origin,
            {**source.source, "copied_from": source.id, "faults": faults},
            created_by,
            created_by_agent,
        )
        await self._store_series(dataset.id, copies.values())
        for original in originals:
            mine = [item for item in planned if item.series.id == original.id]
            copy = copies[original.id]
            await self.session.execute(
                insert(DojoPoint).from_select(
                    list(POINT_COLUMNS),
                    select(
                        literal(copy.id, Text),
                        DojoPoint.timestamp,
                        written_value(mine),
                    ).where(DojoPoint.series_id == original.id, kept(mine)),
                )
            )
            await self._measure(copy)
        intervals = [
            (
                label.start_at,
                label.end_at,
                label.note,
                label.rule,
                label.suggested_by_agent,
            )
            for label in labels
        ]
        intervals += [(*item.interval, item.note(), "", None) for item in planned]
        self.session.add_all(
            DojoLabel(
                id=str(uuid4()),
                dataset_id=dataset.id,
                start_at=start,
                end_at=end,
                note=note,
                rule=rule,
                suggested_by_agent=agent,
                created_by=created_by,
            )
            for start, end, note, rule, agent in intervals
        )
        return await self._finish(dataset, copies.values())

    async def _measure(self, item: _Series) -> None:
        """Read back how many values a series holds and when."""
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

    def _dataset(self, name, description, origin, source, created_by, agent=None):
        dataset = DojoDataset(
            id=str(uuid4()),
            name=self._name(name),
            description=description,
            origin=origin,
            source=source,
            created_by=created_by,
            created_by_agent=agent.name if agent else None,
            created_by_agent_id=agent.id if agent else None,
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
        if not filled:
            raise ValidationError("The dataset contains no values")
        if dataset.point_count > MAX_DATASET_POINTS:
            raise _too_many_points()
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
            created_by_agent=row.created_by_agent,
            created_at=row.created_at,
        )
