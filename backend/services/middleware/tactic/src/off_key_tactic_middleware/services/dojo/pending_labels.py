"""Labels proposed for review: by a condition over a dataset's series, or as
intervals an agent chose.

A pending label scores no run. A member adds it as a label, maybe changed
first, or dismisses it. Members and agents propose the same way, so a rule a
member types and one an agent applies end up side by side for review.
"""

import builtins
import math
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from uuid import uuid4

from off_key_core.db.maintenance import require_application_writes
from off_key_core.db.models import (
    Agent,
    DojoDataset,
    DojoLabel,
    DojoPendingLabel,
    DojoPoint,
    DojoSeries,
    User,
)
from off_key_core.models.pipeline_formula import FormulaError, evaluator, parse
from off_key_core.models.pipeline_prepare import PrepareFailure
from off_key_core.schemas.dojo import (
    MAX_DATASET_LABELS,
    MAX_LABEL_SUGGESTIONS,
    MAX_PENDING_LABELS,
    LabelRule,
    LabelView,
    PendingLabelAccept,
    PendingLabelDismiss,
    PendingLabelList,
    PendingLabelProposal,
    PendingLabelsMade,
    PendingLabelView,
)
from sqlalchemy import delete, func, select

from ...domain import ConflictError, NotFoundError, ValidationError
from .labels import LONE_ALARM, DojoLabels, label_view
from .owners import made_by

Interval = tuple[datetime, datetime]
POINTS_PAGE = 10_000


def pending_view(row: DojoPendingLabel) -> PendingLabelView:
    return PendingLabelView(
        id=row.id,
        dataset_id=row.dataset_id,
        start_at=row.start_at,
        end_at=row.end_at,
        note=row.note,
        rule=row.rule,
        created_by=row.created_by,
        created_by_agent=row.created_by_agent,
        created_at=row.created_at,
    )


class Holds:
    """Where a condition holds, fed the values of its series in time order.

    Each series keeps its last value until its next one; the condition is read
    once all of its series have a value. An interval runs from the first
    instant the condition holds to the last; a lone instant gets a second. A
    value the condition cannot be computed for, such as a division by 0, ends
    no interval and starts none.
    """

    def __init__(self, check: Callable[[dict[str, float]], object], names: int):
        self.check = check
        self.names = names
        self.found: list[Interval] = []
        self.latest: dict[str, float] = {}
        self.instant: datetime | None = None
        self.start: datetime | None = None
        self.last: datetime | None = None

    def feed(self, timestamp: datetime, name: str, value: float) -> None:
        if self.instant is not None and timestamp != self.instant:
            self._read(self.instant)
        self.instant = timestamp
        self.latest[name] = value

    def finish(self) -> list[Interval]:
        if self.instant is not None:
            self._read(self.instant)
            self.instant = None
        self._close()
        return self.found

    def _read(self, instant: datetime) -> None:
        if len(self.latest) < self.names:
            return
        try:
            held = bool(self.check(self.latest))
        except PrepareFailure:
            return
        if held:
            if self.start is None:
                self.start = instant
            self.last = instant
        else:
            self._close()

    def _close(self) -> None:
        if self.start is not None and self.last is not None:
            self.found.append((self.start, max(self.last, self.start + LONE_ALARM)))
        self.start = self.last = None


def shaped(
    intervals: Sequence[Interval], merge_gap: timedelta, min_duration: timedelta
) -> list[Interval]:
    """Join intervals closer than the gap, then leave out the short ones."""
    joined: list[Interval] = []
    for start, end in intervals:
        if joined and start - joined[-1][1] < merge_gap:
            joined[-1] = (joined[-1][0], max(end, joined[-1][1]))
        else:
            joined.append((start, end))
    return [item for item in joined if item[1] - item[0] >= min_duration]


class DojoPendingLabels:
    def __init__(self, session):
        self.session = session
        self.labels = DojoLabels(session)

    async def list(self, dataset_id: str) -> PendingLabelList:
        await self.labels.dataset_row(dataset_id)
        rows = (
            await self.session.scalars(
                select(DojoPendingLabel)
                .where(DojoPendingLabel.dataset_id == dataset_id)
                .order_by(DojoPendingLabel.start_at, DojoPendingLabel.id)
            )
        ).all()
        return PendingLabelList(items=[pending_view(row) for row in rows])

    async def propose(
        self, dataset_id: str, proposal: PendingLabelProposal, caller: User | Agent
    ) -> PendingLabelsMade:
        """Store intervals as pending labels, leaving out those on a label."""
        await require_application_writes(self.session)
        dataset = await self.labels.dataset_row(dataset_id, lock=True)
        for item in proposal.labels:
            self._inside(dataset, item.start_at, item.end_at)
        return await self._store(
            dataset,
            [
                (item.start_at, item.end_at, item.note.strip())
                for item in proposal.labels
            ],
            rule=proposal.rule.strip(),
            caller=caller,
            replace=proposal.replace,
        )

    async def propose_by_rule(
        self, dataset_id: str, rule: LabelRule, caller: User | Agent
    ) -> PendingLabelsMade:
        """Propose a label for every interval where the condition holds."""
        await require_application_writes(self.session)
        dataset = await self.labels.dataset_row(dataset_id, lock=True)
        series = {
            row.name: row.id
            for row in (
                await self.session.scalars(
                    select(DojoSeries)
                    .where(DojoSeries.dataset_id == dataset.id)
                    .order_by(DojoSeries.position)
                )
            ).all()
        }
        try:
            expression = parse(rule.condition, condition=True)
            expression.check_names(list(series))
        except FormulaError as exc:
            raise ValidationError(f"The condition cannot be used: {exc}") from exc
        names = {series[name]: name for name in expression.names}
        check = evaluator(expression)
        # Up to millions of values: read them in pages, never all at once.
        result = await self.session.stream(
            select(DojoPoint.timestamp, DojoPoint.series_id, DojoPoint.value)
            .where(DojoPoint.series_id.in_(list(names)))
            .order_by(DojoPoint.timestamp, DojoPoint.series_id)
            .execution_options(yield_per=POINTS_PAGE)
        )
        found = Holds(check, len(names))
        async for timestamp, series_id, value in result:
            if math.isfinite(value):
                found.feed(timestamp, names[series_id], value)
        intervals = shaped(
            found.finish(),
            timedelta(seconds=rule.merge_gap_seconds),
            timedelta(seconds=rule.min_duration_seconds),
        )
        note = rule.note.strip()
        return await self._store(
            dataset,
            [(start, end, note) for start, end in intervals],
            rule=rule.condition.strip(),
            caller=caller,
            replace=rule.replace,
        )

    async def accept(
        self, dataset_id: str, choice: PendingLabelAccept, *, created_by: int | None
    ) -> builtins.list[LabelView]:
        """Add pending labels as labels, all of them or none."""
        await require_application_writes(self.session)
        dataset = await self.labels.dataset_row(dataset_id, lock=True)
        rows = await self._rows(dataset.id, [item.id for item in choice.items])
        count = await self.session.scalar(
            select(func.count()).where(DojoLabel.dataset_id == dataset.id)
        )
        if count + len(rows) > MAX_DATASET_LABELS:
            raise ConflictError(f"A dataset holds at most {MAX_DATASET_LABELS} labels")
        added = []
        for item in choice.items:
            pending = rows[item.id]
            start_at = item.start_at or pending.start_at
            end_at = item.end_at or pending.end_at
            if end_at <= start_at:
                raise ValidationError("end_at must be after start_at")
            # Earlier labels of this batch are flushed before the check.
            await self.labels.check_free(dataset, start_at, end_at, None)
            label = DojoLabel(
                id=str(uuid4()),
                dataset_id=dataset.id,
                start_at=start_at,
                end_at=end_at,
                note=(pending.note if item.note is None else item.note).strip(),
                rule=pending.rule,
                suggested_by_agent=pending.created_by_agent,
                created_by=created_by,
            )
            self.session.add(label)
            await self.session.delete(pending)
            added.append(label.id)
        await self.session.commit()
        return [
            label_view(
                await self.session.get(DojoLabel, label_id, populate_existing=True)
            )
            for label_id in added
        ]

    async def dismiss(self, dataset_id: str, dismissal: PendingLabelDismiss) -> None:
        await require_application_writes(self.session)
        dataset = await self.labels.dataset_row(dataset_id, lock=True)
        rows = await self._rows(dataset.id, dismissal.ids)
        for row in rows.values():
            await self.session.delete(row)
        await self.session.commit()

    async def _store(
        self,
        dataset: DojoDataset,
        intervals: Sequence[tuple[datetime, datetime, str]],
        *,
        rule: str,
        caller: User | Agent,
        replace: bool,
    ) -> PendingLabelsMade:
        truncated = False
        replaced = 0
        if replace:
            replaced = (
                await self.session.execute(
                    delete(DojoPendingLabel).where(
                        DojoPendingLabel.dataset_id == dataset.id,
                        made_by(
                            caller,
                            DojoPendingLabel.created_by,
                            DojoPendingLabel.created_by_agent_id,
                        ),
                    )
                )
            ).rowcount
        labels = (
            await self.session.execute(
                select(DojoLabel.start_at, DojoLabel.end_at).where(
                    DojoLabel.dataset_id == dataset.id
                )
            )
        ).all()
        free = [
            item
            for item in intervals
            if not any(start < item[1] and end > item[0] for start, end in labels)
        ]
        skipped = len(intervals) - len(free)
        if len(free) > MAX_LABEL_SUGGESTIONS:
            free, truncated = free[:MAX_LABEL_SUGGESTIONS], True
        waiting = await self.session.scalar(
            select(func.count()).where(DojoPendingLabel.dataset_id == dataset.id)
        )
        if waiting + len(free) > MAX_PENDING_LABELS:
            raise ConflictError(
                f"A dataset holds at most {MAX_PENDING_LABELS} pending labels; "
                "add or dismiss some first"
            )
        agent = caller if isinstance(caller, Agent) else None
        rows = [
            DojoPendingLabel(
                id=str(uuid4()),
                dataset_id=dataset.id,
                start_at=start,
                end_at=end,
                note=note,
                rule=rule,
                created_by=None if agent else caller.id,
                created_by_agent=agent.name if agent else None,
                created_by_agent_id=agent.id if agent else None,
            )
            for start, end, note in free
        ]
        self.session.add_all(rows)
        await self.session.commit()
        made = []
        for row in rows:
            await self.session.refresh(row)
            made.append(pending_view(row))
        return PendingLabelsMade(
            items=made, skipped=skipped, truncated=truncated, replaced=replaced
        )

    async def _rows(
        self, dataset_id: str, ids: Sequence[str]
    ) -> dict[str, DojoPendingLabel]:
        if len(set(ids)) != len(ids):
            raise ValidationError("Name each pending label once")
        rows = {
            row.id: row
            for row in (
                await self.session.scalars(
                    select(DojoPendingLabel).where(
                        DojoPendingLabel.dataset_id == dataset_id,
                        DojoPendingLabel.id.in_(list(ids)),
                    )
                )
            ).all()
        }
        if len(rows) != len(ids):
            raise NotFoundError(
                "Pending label not found; it may have been added or dismissed"
            )
        return rows

    @staticmethod
    def _inside(dataset: DojoDataset, start_at: datetime, end_at: datetime) -> None:
        if (
            dataset.start_at is not None
            and dataset.end_at is not None
            and (end_at < dataset.start_at or start_at > dataset.end_at)
        ):
            raise ValidationError(
                "The label lies outside the dataset, which spans "
                f"{dataset.start_at.isoformat()} to {dataset.end_at.isoformat()}"
            )
