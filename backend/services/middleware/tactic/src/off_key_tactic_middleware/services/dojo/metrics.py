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
from typing import Literal

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
from .diagnostics import alone, run_diagnostics
from .labels import dataset_labels, label_view
from .score_metrics import score_metrics

DAY_SECONDS = 86_400.0
METRICS_TIMEOUT_SECONDS = 30.0
# How long a metrics transaction may run its statements, and of that the score
# metrics at most.
STATEMENT_TIMEOUT = "25s"
SCORES_TIMEOUT = "12s"
TIMED_OUT = "Dojo metrics exceeded the calculation time limit"
# PostgreSQL's query_canceled, which statement_timeout raises.
QUERY_CANCELED = "57014"


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
    alarm_share: float | None = None
    chance_detections: float | None = None
    adjusted_detection_rate: float | None = None


def by_chance(
    evaluation: Evaluation,
    inside: Sequence[int],
    outside_scored: int,
    outside_alarms: int,
) -> Evaluation:
    """The evaluation with what its alarm rate would detect by chance.

    An alarm share a outside the labels, scattered at random, hits a label of
    n scored results with probability 1 - (1 - a)^n. Detections beyond that
    sum are the run's own (Kim et al., AAAI 2022, on how event credit lets
    random scores look good).
    """
    share = _rate(outside_alarms, outside_scored)
    labels = []
    chance = 0.0
    for outcome, results in zip(evaluation.labels, inside, strict=True):
        hit = None if share is None else 1 - (1 - share) ** results
        if hit is not None and outcome.outcome != "unscored":
            chance += hit
        labels.append(outcome.model_copy(update={"results": results, "chance": hit}))
    adjusted = None
    if share is not None and evaluation.labels_scored - chance > 1e-9:
        adjusted = (evaluation.labels_detected - chance) / (
            evaluation.labels_scored - chance
        )
    return replace(
        evaluation,
        labels=labels,
        alarm_share=share,
        chance_detections=None if share is None else chance,
        adjusted_detection_rate=adjusted,
    )


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


def _cache_key(run: DojoRun, labels: Sequence[DojoLabel], kind: str) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                6,
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


def _from_cache(run: DojoRun, kind: str, key: str) -> dict | None:
    """The cached value of one metrics product, if it was stored under ``key``."""
    cache = (run.metrics_cache or {}).get(kind, {})
    return cache["value"] if cache.get("key") == key else None


async def _statement_timeout(session, limit: str) -> None:
    await session.execute(text(f"SET LOCAL statement_timeout = '{limit}'"))


def _timed_out(exc: DBAPIError) -> bool:
    return getattr(exc.orig, "sqlstate", None) == QUERY_CANCELED


def _intervals(labels: Sequence[DojoLabel]) -> list[Interval]:
    return [Interval(label.id, label.start_at, label.end_at) for label in labels]


def _delays(evaluation: Evaluation) -> list[float]:
    return [
        item.delay_seconds
        for item in evaluation.labels
        if item.delay_seconds is not None
    ]


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


def _unusual(run: DojoRun) -> Literal["high", "low"]:
    """A static baseline stores p-values: the low ones are unusual."""
    kind = result_kind(run.config["execution"]["definition"])
    return "low" if kind == "static_baseline" else "high"


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
            raise ConflictError(TIMED_OUT) from None

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
            measured = [await self._metrics(run, labels) for run in runs]
            return Comparison(
                dataset_id=dataset.id,
                labels=[label_view(label) for label in labels],
                runs=await alone(self.session, measured),
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

    @staticmethod
    def cached(run: DojoRun, labels: list[DojoLabel]) -> RunMetrics | None:
        """The run's metrics if they were calculated against these labels."""
        if run.status != "succeeded":
            return None
        value = _from_cache(run, "run", _cache_key(run, labels, "run"))
        return None if value is None else RunMetrics.model_validate(value)

    async def calculate(
        self, run: DojoRun, labels: list[DojoLabel]
    ) -> RunMetrics | None:
        """Calculate a finished run's metrics, or none while another
        calculation holds the slot or this one runs out of time."""
        try:
            async with self._budget():
                return await self._metrics(run, labels)
        except ConflictError:
            return None

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
        key = _cache_key(run, labels, kind)
        if (value := _from_cache(run, kind, key)) is not None:
            return model.model_validate(value)
        # One uncached scan across all replicas; readers never queue for a slot.
        if not await self.session.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": DOJO_METRICS_LOCK}
        ):
            raise ConflictError("Dojo metrics are being calculated; retry shortly")
        try:
            await _statement_timeout(self.session, STATEMENT_TIMEOUT)
            # Another request may have committed after our initial read. Preserve
            # its other metrics product and reuse its result if the key matches.
            await self.session.refresh(run, attribute_names=["metrics_cache"])
            if (value := _from_cache(run, kind, key)) is not None:
                result = model.model_validate(value)
            else:
                result = await calculate(run, labels)
                run.metrics_cache = (run.metrics_cache or {}) | {
                    kind: {"key": key, "value": result.model_dump(mode="json")}
                }
            await self.session.commit()
            return result
        except DBAPIError as exc:
            await self.session.rollback()
            if _timed_out(exc):
                raise ConflictError(TIMED_OUT) from None
            raise
        except BaseException:
            await self.session.rollback()
            raise

    async def _calculate(self, run: DojoRun, labels: list[DojoLabel]) -> RunMetrics:
        scan = await self._scan(run.id, _intervals(labels))
        evaluation, _ = scan.evaluations[0]
        delays = _delays(evaluation)
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
            alarm_share=evaluation.alarm_share,
            chance_detections=evaluation.chance_detections,
            adjusted_detection_rate=evaluation.adjusted_detection_rate,
            scores=await self._scores(run, labels),
            diagnostics=await self._limited(
                run_diagnostics(
                    self.session,
                    run.id,
                    run.config.get("series", []),
                    unusual=_unusual(run),
                )
            ),
            labels=evaluation.labels,
        )

    async def _scores(self, run: DojoRun, labels: list[DojoLabel]):
        """Score metrics within their own time limit, or none past it.

        They sort every scored result, which on the largest runs takes
        seconds; the event metrics must still come back when they cannot.
        """
        return await self._limited(
            score_metrics(
                self.session,
                run.id,
                [(label.start_at, label.end_at) for label in labels],
                unusual=_unusual(run),
            )
        )

    async def _limited[T](self, calculation: Awaitable[T]) -> T | None:
        """A calculation within SCORES_TIMEOUT, or None past it."""
        try:
            async with self.session.begin_nested():
                await _statement_timeout(self.session, SCORES_TIMEOUT)
                result = await calculation
                await _statement_timeout(self.session, STATEMENT_TIMEOUT)
                return result
        except DBAPIError as exc:
            if not _timed_out(exc):
                raise
            # Rolling back to the savepoint restored the transaction's limit.
            return None

    async def _calibration(
        self, run: DojoRun, labels: list[DojoLabel]
    ) -> MethodComparison:
        plan = run.config["calibration_comparison"]
        scan = await self._scan(
            run.id, _intervals(labels), method_count=len(plan["methods"])
        )
        failed = plan.get("failed", {})
        methods = []
        for position, method in enumerate([plan["own"], *plan["methods"]]):
            evaluation, alarm_count = scan.evaluations[position]
            # A method that stopped retains its counts, but has no full-run rate.
            stopped = method in failed
            delays = _delays(evaluation)
            name, family = (
                ("Fixed split", "fixed")
                if method == FIXED_METHOD
                else (CALIBRATORS[method]["name"], CALIBRATORS[method]["family"])
            )
            methods.append(
                MethodMetrics(
                    method=method,
                    name=name,
                    family=family,
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
            func.count().filter(c.score.is_not(None)),
        ).group_by(group)
        if method_count is not None:
            statement = statement.where(c.method_alarms.is_not(None))
        rows = (await self.session.execute(statement)).all()
        scored_from = min((row[1] for row in rows if row[1] is not None), default=None)
        scored_to = max((row[2] for row in rows if row[2] is not None), default=None)
        scored = {row[0]: row[-1] for row in rows}
        outside = [row for row in rows if row[0] == 0]
        inside = [scored.get(index, 0) for index in range(1, len(labels) + 1)]
        outside_scored = sum(row[-1] for row in outside)
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
            evaluation = by_chance(
                evaluate(labels, first, scored_from, scored_to),
                inside,
                outside_scored,
                sum(row[offset + 1] for row in outside),
            )
            evaluations.append(
                (
                    replace(
                        evaluation,
                        false_alarms=sum(row[offset + 2] for row in outside),
                    ),
                    sum(row[offset + 1] for row in rows),
                )
            )
        return Scan(scored_from, scored_to, sum(row[3] for row in rows), evaluations)
