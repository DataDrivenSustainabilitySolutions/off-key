"""Score finished Dojo runs against their dataset's labels.

Metrics are computed when they are read, from the stored results and the
current labels, so a corrected label re-scores every run without a replay.
Only alarm rows leave the database: one ordered pass marks where each alarm
begins, and everything else is arithmetic over the labels.
"""

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from statistics import median

from aberration_core.db.models import DojoDataset, DojoLabel, DojoRun, DojoRunResult
from aberration_core.schemas.dojo import (
    Comparison,
    ComparisonQuery,
    LabelOutcome,
    RunMetrics,
)
from sqlalchemy import false, func, select

from ...domain import ConflictError, NotFoundError, ValidationError
from .labels import dataset_labels, label_view

DAY_SECONDS = 86_400.0


@dataclass(frozen=True)
class Interval:
    id: str
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True)
class Alarm:
    timestamp: datetime
    # True where the previous result did not alarm.
    onset: bool


@dataclass(frozen=True)
class Evaluation:
    labels: list[LabelOutcome]
    labels_scored: int
    labels_detected: int
    false_alarms: int
    evaluated_seconds: float


def evaluate(
    labels: Sequence[Interval],
    alarms: Sequence[Alarm],
    scored_from: datetime | None,
    scored_to: datetime | None,
) -> Evaluation:
    """Event metrics for non-overlapping ``labels``, both inputs in time order.

    A label counts as detected when any alarm falls inside it, ends included.
    An alarm onset outside every label is one false alarm; an alarm that
    starts inside a label and outlasts it is not counted again.
    """
    starts = [label.start_at for label in labels]
    first: list[datetime | None] = [None] * len(labels)
    false_alarms = 0
    for alarm in alarms:
        index = bisect_right(starts, alarm.timestamp) - 1
        if index >= 0 and alarm.timestamp <= labels[index].end_at:
            if first[index] is None:
                first[index] = alarm.timestamp
        elif alarm.onset:
            false_alarms += 1

    outcomes = []
    scored = detected = 0
    covered = 0.0
    for label, first_alarm in zip(labels, first, strict=True):
        overlap = _overlap(label, scored_from, scored_to)
        covered += overlap
        if first_alarm is not None:
            outcome = "detected"
        elif (
            scored_from is not None
            and scored_to is not None
            and (label.end_at >= scored_from and label.start_at <= scored_to)
        ):
            outcome = "missed"
        else:
            outcome = "unscored"
        if outcome != "unscored":
            scored += 1
        if outcome == "detected":
            detected += 1
        outcomes.append(
            LabelOutcome(
                label_id=label.id,
                start_at=label.start_at,
                end_at=label.end_at,
                outcome=outcome,
                first_alarm_at=first_alarm,
                delay_seconds=(
                    (first_alarm - label.start_at).total_seconds()
                    if first_alarm is not None
                    else None
                ),
            )
        )
    span = (
        (scored_to - scored_from).total_seconds()
        if scored_from is not None and scored_to is not None
        else 0.0
    )
    return Evaluation(
        labels=outcomes,
        labels_scored=scored,
        labels_detected=detected,
        false_alarms=false_alarms,
        evaluated_seconds=max(span - covered, 0.0),
    )


def _overlap(label: Interval, start: datetime | None, end: datetime | None) -> float:
    if start is None or end is None:
        return 0.0
    lower = max(label.start_at, start)
    upper = min(label.end_at, end)
    return max((upper - lower).total_seconds(), 0.0)


class DojoMetrics:
    def __init__(self, session):
        self.session = session

    async def run(self, run_id: str) -> RunMetrics:
        run = await self._run(run_id)
        labels = await dataset_labels(self.session, run.dataset_id)
        return await self._metrics(run, labels)

    async def compare(self, dataset_id: str, query: ComparisonQuery) -> Comparison:
        dataset = await self.session.get(DojoDataset, dataset_id)
        if dataset is None:
            raise NotFoundError("Dataset not found")
        runs = [await self._run(run_id) for run_id in query.run_ids]
        elsewhere = [run.id for run in runs if run.dataset_id != dataset.id]
        if elsewhere:
            raise ValidationError(
                "Compare runs of one dataset; "
                f"{', '.join(map(repr, elsewhere))} ran on another"
            )
        labels = await dataset_labels(self.session, dataset.id)
        return Comparison(
            dataset_id=dataset.id,
            labels=[label_view(label) for label in labels],
            runs=[await self._metrics(run, labels) for run in runs],
        )

    async def _run(self, run_id: str) -> DojoRun:
        run = await self.session.get(DojoRun, run_id)
        if run is None:
            raise NotFoundError("Run not found")
        if run.status != "succeeded":
            raise ConflictError(
                f"Run {run.id!r} is {run.status}; only a finished run has metrics"
            )
        return run

    async def _metrics(self, run: DojoRun, labels: list[DojoLabel]) -> RunMetrics:
        scored_from, scored_to = (
            await self.session.execute(
                select(
                    func.min(DojoRunResult.timestamp).filter(
                        DojoRunResult.score.is_not(None)
                    ),
                    func.max(DojoRunResult.timestamp),
                ).where(DojoRunResult.run_id == run.id)
            )
        ).one()
        evaluation = evaluate(
            [Interval(label.id, label.start_at, label.end_at) for label in labels],
            await self._alarms(run.id),
            scored_from,
            scored_to,
        )
        delays = [
            item.delay_seconds
            for item in evaluation.labels
            if item.delay_seconds is not None
        ]
        return RunMetrics(
            run_id=run.id,
            run_name=run.name,
            strategy=run.config["execution"]["definition"]["strategy"],
            scored_from=scored_from,
            scored_to=scored_to,
            labels_total=len(labels),
            labels_scored=evaluation.labels_scored,
            labels_detected=evaluation.labels_detected,
            detection_rate=(
                evaluation.labels_detected / evaluation.labels_scored
                if evaluation.labels_scored
                else None
            ),
            median_delay_seconds=median(delays) if delays else None,
            max_delay_seconds=max(delays) if delays else None,
            alarm_count=run.alarm_count,
            false_alarms=evaluation.false_alarms,
            evaluated_seconds=evaluation.evaluated_seconds,
            false_alarms_per_day=(
                evaluation.false_alarms * DAY_SECONDS / evaluation.evaluated_seconds
                if evaluation.evaluated_seconds > 0
                else None
            ),
            labels=evaluation.labels,
        )

    async def _alarms(self, run_id: str) -> list[Alarm]:
        previous = func.lag(DojoRunResult.alarm).over(order_by=DojoRunResult.sequence)
        ordered = (
            select(
                DojoRunResult.sequence,
                DojoRunResult.timestamp,
                DojoRunResult.alarm,
                func.coalesce(previous, false()).label("previous"),
            )
            .where(DojoRunResult.run_id == run_id)
            .subquery()
        )
        rows = (
            await self.session.execute(
                select(ordered.c.timestamp, ordered.c.previous)
                .where(ordered.c.alarm)
                .order_by(ordered.c.sequence)
            )
        ).all()
        return [Alarm(timestamp, not previous) for timestamp, previous in rows]
