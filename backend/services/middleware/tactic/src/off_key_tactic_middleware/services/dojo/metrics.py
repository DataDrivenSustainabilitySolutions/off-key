"""Score finished Dojo runs against their dataset's labels.

Metrics are computed when they are read, from the stored results and the
current labels, so a corrected label re-scores every run without a replay.
Only one aggregate per label leaves the database. Both metrics products are
cached until labels change, with a shared scan limit and calculation deadlines.

A run that tried other calibration methods kept, for each result, which of
them would have alarmed. Each method is scored like a run of its own.
"""

import asyncio
import hashlib
import json
from bisect import bisect_right
from collections.abc import Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from statistics import median

from off_key_core.db.locks import DOJO_METRICS_LOCK
from off_key_core.db.models import DojoDataset, DojoLabel, DojoRun, DojoRunResult
from off_key_core.models.dojo_runs import FIXED_METHOD, result_kind
from off_key_core.models.pipeline_calibration import CALIBRATORS
from off_key_core.schemas.dojo import (
    Comparison,
    ComparisonQuery,
    LabelOutcome,
    MethodComparison,
    MethodMetrics,
    RunMetrics,
)
from pydantic import BaseModel
from sqlalchemy import DateTime, case, false, func, literal, select, text
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.exc import DBAPIError

from ...domain import ConflictError, NotFoundError, ValidationError
from .labels import dataset_labels, label_view

DAY_SECONDS = 86_400.0
METRICS_TIMEOUT_SECONDS = 30.0


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


def _rate(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _per_day(evaluation: Evaluation) -> float | None:
    if evaluation.evaluated_seconds <= 0:
        return None
    return evaluation.false_alarms * DAY_SECONDS / evaluation.evaluated_seconds


@dataclass(frozen=True)
class Scan:
    scored_from: datetime | None
    scored_to: datetime | None
    results: int
    evaluations: list[tuple[Evaluation, int]]


class DojoMetrics:
    def __init__(self, session):
        self.session = session

    @asynccontextmanager
    async def _budget(self):
        try:
            async with asyncio.timeout(METRICS_TIMEOUT_SECONDS):
                yield
        except TimeoutError:
            await self.session.rollback()
            raise ConflictError(
                "Dojo metrics exceeded the calculation time limit"
            ) from None

    async def run(self, run_id: str) -> RunMetrics:
        async with self._budget():
            run = await self._run(run_id)
            labels = await dataset_labels(self.session, run.dataset_id)
            return await self._metrics(run, labels)

    async def compare(self, dataset_id: str, query: ComparisonQuery) -> Comparison:
        async with self._budget():
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

    async def calibration(self, run_id: str) -> MethodComparison:
        """The run's own calibration step beside every method it also tried."""
        async with self._budget():
            run = await self._run(run_id)
            if run.config.get("calibration_comparison") is None:
                raise ConflictError(
                    "The run compared no calibration methods; start a run that does"
                )
            labels = await dataset_labels(self.session, run.dataset_id)
            return await self._cached(
                run, labels, "calibration", MethodComparison, self._calibration
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
        return await self._cached(run, labels, "run", RunMetrics, self._calculate)

    async def _cached[T: BaseModel](
        self,
        run: DojoRun,
        labels: list[DojoLabel],
        kind: str,
        model: type[T],
        calculate: Callable[[DojoRun, list[DojoLabel]], Awaitable[T]],
    ) -> T:
        key = hashlib.sha256(
            json.dumps(
                [
                    1,
                    run.result_count,
                    run.alarm_count,
                    run.config.get("calibration_comparison")
                    if kind == "calibration"
                    else None,
                    [
                        (label.id, label.start_at.isoformat(), label.end_at.isoformat())
                        for label in labels
                    ],
                ],
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        cache = (run.metrics_cache or {}).get(kind, {})
        if cache.get("key") == key:
            return model.model_validate(cache["value"])
        # One uncached scan across all replicas; readers never queue for a slot.
        if not await self.session.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": DOJO_METRICS_LOCK}
        ):
            raise ConflictError("Dojo metrics are being calculated; retry shortly")
        try:
            await self.session.execute(text("SET LOCAL statement_timeout = '25s'"))
            # Another request may have committed after our initial read. Preserve
            # its other metrics product and reuse its result if the key matches.
            await self.session.refresh(run, attribute_names=["metrics_cache"])
            cache = (run.metrics_cache or {}).get(kind, {})
            if cache.get("key") == key:
                result = model.model_validate(cache["value"])
            else:
                result = await calculate(run, labels)
                run.metrics_cache = (run.metrics_cache or {}) | {
                    kind: {"key": key, "value": result.model_dump(mode="json")}
                }
            await self.session.commit()
            return result
        except DBAPIError as exc:
            await self.session.rollback()
            if getattr(exc.orig, "sqlstate", None) == "57014":
                raise ConflictError(
                    "Dojo metrics exceeded the calculation time limit"
                ) from None
            raise
        except BaseException:
            await self.session.rollback()
            raise

    async def _calculate(self, run: DojoRun, labels: list[DojoLabel]) -> RunMetrics:
        scan = await self._scan(
            run.id,
            [Interval(label.id, label.start_at, label.end_at) for label in labels],
        )
        evaluation, _ = scan.evaluations[0]
        delays = [
            item.delay_seconds
            for item in evaluation.labels
            if item.delay_seconds is not None
        ]
        return RunMetrics(
            run_id=run.id,
            run_name=run.name,
            strategy=result_kind(run.config["execution"]["definition"]),
            scored_from=scan.scored_from,
            scored_to=scan.scored_to,
            labels_total=len(labels),
            labels_scored=evaluation.labels_scored,
            labels_detected=evaluation.labels_detected,
            detection_rate=_rate(evaluation.labels_detected, evaluation.labels_scored),
            median_delay_seconds=median(delays) if delays else None,
            max_delay_seconds=max(delays) if delays else None,
            alarm_count=run.alarm_count,
            false_alarms=evaluation.false_alarms,
            evaluated_seconds=evaluation.evaluated_seconds,
            false_alarms_per_day=_per_day(evaluation),
            labels=evaluation.labels,
        )

    async def _calibration(
        self, run: DojoRun, labels: list[DojoLabel]
    ) -> MethodComparison:
        plan = run.config["calibration_comparison"]
        scan = await self._scan(
            run.id,
            [Interval(label.id, label.start_at, label.end_at) for label in labels],
            method_count=len(plan["methods"]),
        )
        failed = plan.get("failed", {})
        methods = []
        for position, method in enumerate([plan["own"], *plan["methods"]]):
            evaluation, alarm_count = scan.evaluations[position]
            # A method that stopped retains its counts, but has no full-run rate.
            stopped = method in failed
            delays = [
                item.delay_seconds
                for item in evaluation.labels
                if item.delay_seconds is not None
            ]
            methods.append(
                MethodMetrics(
                    method=method,
                    name=(
                        "Fixed split"
                        if method == FIXED_METHOD
                        else CALIBRATORS[method]["name"]
                    ),
                    family=(
                        "fixed"
                        if method == FIXED_METHOD
                        else CALIBRATORS[method]["family"]
                    ),
                    own=position == 0,
                    failed=failed.get(method),
                    alarm_count=alarm_count,
                    alarm_share=None if stopped else _rate(alarm_count, scan.results),
                    labels_scored=evaluation.labels_scored,
                    labels_detected=evaluation.labels_detected,
                    detection_rate=(
                        None
                        if stopped
                        else _rate(evaluation.labels_detected, evaluation.labels_scored)
                    ),
                    median_delay_seconds=median(delays) if delays else None,
                    false_alarms=evaluation.false_alarms,
                    false_alarms_per_day=None if stopped else _per_day(evaluation),
                )
            )
        return MethodComparison(
            run_id=run.id,
            run_name=run.name,
            alpha=plan["alpha"],
            consecutive=plan["consecutive"],
            results=scan.results,
            scored_from=scan.scored_from,
            scored_to=scan.scored_to,
            labels_total=len(labels),
            evaluated_seconds=scan.evaluations[0][0].evaluated_seconds,
            methods=methods,
        )

    async def _scan(
        self, run_id: str, labels: list[Interval], method_count: int | None = None
    ) -> Scan:
        # Windows run before filtering judged rows. One aggregate per label
        # leaves PostgreSQL, even when all five million results/methods alarm.
        order = DojoRunResult.sequence
        columns = [
            DojoRunResult.timestamp,
            DojoRunResult.score,
            DojoRunResult.alarm,
            func.coalesce(
                func.lag(DojoRunResult.alarm).over(order_by=order), false()
            ).label("alarm_before"),
        ]
        if method_count is not None:
            columns.extend(
                [
                    DojoRunResult.method_alarms,
                    func.coalesce(
                        func.lag(DojoRunResult.method_alarms).over(order_by=order), 0
                    ).label("methods_before"),
                ]
            )
        ordered = select(*columns).where(DojoRunResult.run_id == run_id).subquery()
        c = ordered.c
        group = literal(0)
        if labels:
            starts = array(
                [label.start_at for label in labels], type_=DateTime(timezone=True)
            )
            ends = array(
                [label.end_at for label in labels], type_=DateTime(timezone=True)
            )
            # Binary search matches evaluate(): inclusive ends, later label at
            # touching boundaries, and zero for rows outside every label.
            bucket = func.width_bucket(c.timestamp, starts)
            group = case((c.timestamp <= ends[bucket], bucket), else_=0)
        alarm_columns = [(c.alarm, c.alarm_before)]
        if method_count is not None:
            alarm_columns.extend(
                (
                    c.method_alarms.bitwise_and(1 << i) != 0,
                    c.methods_before.bitwise_and(1 << i) != 0,
                )
                for i in range(method_count)
            )
        aggregates = []
        for alarm, before in alarm_columns:
            aggregates.extend(
                [
                    func.min(c.timestamp).filter(alarm),
                    func.count().filter(alarm),
                    func.count().filter(alarm & ~before),
                ]
            )
        statement = select(
            group.label("label_index"),
            func.min(c.timestamp).filter(c.score.is_not(None))
            if method_count is None
            else func.min(c.timestamp),
            func.max(c.timestamp),
            func.count(),
            *aggregates,
        ).group_by(group)
        if method_count is not None:
            statement = statement.where(c.method_alarms.is_not(None))
        rows = (await self.session.execute(statement)).all()
        scored_from = min((row[1] for row in rows if row[1] is not None), default=None)
        scored_to = max((row[2] for row in rows if row[2] is not None), default=None)
        evaluations = []
        for position in range(len(alarm_columns)):
            offset = 4 + position * 3
            first = sorted(
                [
                    Alarm(row[offset], False)
                    for row in rows
                    if row[0] and row[offset] is not None
                ],
                key=lambda alarm: alarm.timestamp,
            )
            evaluation = evaluate(labels, first, scored_from, scored_to)
            evaluations.append(
                (
                    replace(
                        evaluation,
                        false_alarms=sum(
                            row[offset + 2] for row in rows if row[0] == 0
                        ),
                    ),
                    sum(row[offset + 1] for row in rows),
                )
            )
        return Scan(scored_from, scored_to, sum(row[3] for row in rows), evaluations)
