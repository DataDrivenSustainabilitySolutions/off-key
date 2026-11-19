"""Benchmark suites and studies: test designs on many labelled datasets.

A benchmark suite fixes labelled datasets to test designs on, again and
again, in the sense of OpenML's benchmark suites: its datasets never change,
so its studies stay comparable. A study replays one design over every
dataset of a suite, one ordinary run each, and adds up their metrics. The
suite ranks its complete studies, and two studies compare dataset by dataset
with a Wilcoxon signed-rank test (Demšar 2006).

A suite a key made waits for a member's review: an agent should not be the
only judge of the test it is scored on.
"""

import math
import random
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from statistics import mean, median
from typing import cast
from uuid import uuid4

from off_key_core.config.logs import log_security_event
from off_key_core.db.maintenance import require_application_writes
from off_key_core.db.models import (
    Agent,
    DojoDataset,
    DojoLabel,
    DojoPoint,
    DojoRun,
    DojoRunResult,
    DojoSeries,
    DojoStudy,
    DojoSuite,
    DojoSuiteDataset,
    User,
)
from off_key_core.models.dojo_runs import result_kind
from off_key_core.schemas.dojo import (
    MAX_SUITE_STUDIES,
    DatasetOrigin,
    DatasetWithFaults,
    Fault,
    FaultSuiteCreate,
    PairedDataset,
    RunAlignment,
    RunMetrics,
    RunStatus,
    StudyComparison,
    StudyComparisonQuery,
    StudyCreate,
    StudyItem,
    StudyListPage,
    StudyListQuery,
    StudyMetric,
    StudySummary,
    StudyTotals,
    StudyView,
    SuiteChange,
    SuiteCreate,
    SuiteDataset,
    SuiteListPage,
    SuiteListQuery,
    SuiteSummary,
    SuiteView,
)
from sqlalchemy import delete, func, select

from ...domain import ConflictError, ForbiddenError, NotFoundError, ValidationError
from .datasets import DojoDatasets
from .labels import dataset_labels
from .metrics import DojoMetrics
from .owners import made_by, require_no_evidence
from .runs import ACTIVE, DojoRuns, compile_design, dataset_series

# Reading a study calculates the metrics of its finished runs for at most
# this long; the rest wait for the next read.
CALCULATE_SECONDS = 8.0
# A drawn fault lasts this share of the dataset's span, and at least this many
# typical intervals between values, so a detector has values to see it in.
FAULT_SHARE = (0.005, 0.03)
FAULT_VALUES = 5
# A drawn step or drift moves the values by this many standard deviations of
# the series, up or down: from barely visible to plain.
FAULT_SIGMAS = (2.0, 5.0)
# Draws of one copy that land on no values are drawn again, this many times.
FAULT_ATTEMPTS = 20


class DojoSuites:
    def __init__(self, session):
        self.session = session

    # Suites

    async def create_suite(
        self,
        request: SuiteCreate,
        *,
        created_by: int | None,
        created_by_agent: Agent | None = None,
    ) -> SuiteView:
        await require_application_writes(self.session)
        if request.derived_from is not None:
            await self._suite(request.derived_from)
        await self._require_datasets(request.dataset_ids)
        row = DojoSuite(
            id=str(uuid4()),
            name=request.name.strip(),
            description=request.description.strip(),
            derived_from=request.derived_from,
            created_by=created_by,
            created_by_agent=created_by_agent.name if created_by_agent else None,
            created_by_agent_id=created_by_agent.id if created_by_agent else None,
            # A member's own suite counts as reviewed by them.
            reviewed_by=None if created_by_agent else created_by,
            reviewed_at=None if created_by_agent else datetime.now(UTC),
        )
        self.session.add(row)
        await self.session.flush()
        self.session.add_all(
            DojoSuiteDataset(suite_id=row.id, dataset_id=dataset_id, position=position)
            for position, dataset_id in enumerate(request.dataset_ids)
        )
        await self.session.commit()
        return await self.get_suite(row.id)

    async def create_fault_suite(
        self,
        request: FaultSuiteCreate,
        *,
        created_by: int | None,
        created_by_agent: Agent | None = None,
    ) -> SuiteView:
        """Copies of one dataset with faults written in at random places drawn
        from ``seed``, gathered into a suite. The source's own labels stay in
        every copy, and no fault overlaps them or another fault."""
        await require_application_writes(self.session)
        datasets = DojoDatasets(self.session)
        source = await datasets.get(request.dataset_id)
        unknown = sorted(set(request.series) - {item.name for item in source.series})
        if unknown:
            raise ValidationError(
                f"The dataset has no series named {', '.join(unknown)}"
            )
        targets = [
            item
            for item in source.series
            if item.point_count and (not request.series or item.name in request.series)
        ]
        if not targets or source.start_at is None or source.end_at is None:
            raise ValidationError("The dataset holds no values to write faults into")
        spreads = {
            series_id: spread
            for series_id, spread in (
                await self.session.execute(
                    select(DojoPoint.series_id, func.stddev_samp(DojoPoint.value))
                    .where(DojoPoint.series_id.in_([item.id for item in targets]))
                    .group_by(DojoPoint.series_id)
                )
            ).all()
        }
        taken = [
            (label.start_at, label.end_at)
            for label in await dataset_labels(self.session, source.id)
        ]
        draw = random.Random(request.seed)
        made: list[str] = []
        try:
            for number in range(1, request.copies + 1):
                for attempt in range(1, FAULT_ATTEMPTS + 1):
                    faults = _draw_faults(
                        draw,
                        request,
                        source.start_at,
                        source.end_at,
                        targets,
                        spreads,
                        taken,
                    )
                    try:
                        copy = await datasets.inject_faults(
                            source.id,
                            DatasetWithFaults(
                                name=f"{request.name} · copy {number}",
                                description=f"Seed {request.seed}, copy {number}",
                                faults=faults,
                            ),
                            created_by=created_by,
                            created_by_agent=created_by_agent,
                        )
                    except ValidationError:
                        await self.session.rollback()
                        if attempt == FAULT_ATTEMPTS:
                            raise
                        continue
                    made.append(copy.id)
                    break
            return await self.create_suite(
                SuiteCreate(
                    name=request.name,
                    description=request.description
                    or (
                        f"{request.copies} copies of {source.name} with "
                        f"{request.faults_per_copy} drawn faults each, seed "
                        f"{request.seed}"
                    ),
                    dataset_ids=made,
                ),
                created_by=created_by,
                created_by_agent=created_by_agent,
            )
        except BaseException:
            await self.session.rollback()
            for dataset_id in made:
                await datasets.remove(dataset_id)
            raise

    async def list_suites(
        self, query: SuiteListQuery, caller: User | Agent | None = None
    ) -> SuiteListPage:
        statement = select(DojoSuite)
        if query.mine and caller is not None:
            statement = statement.where(
                made_by(caller, DojoSuite.created_by, DojoSuite.created_by_agent_id)
            )
        rows = (
            await self.session.scalars(
                statement.order_by(DojoSuite.created_at.desc(), DojoSuite.id)
                .offset(query.offset)
                .limit(query.limit + 1)
            )
        ).all()
        page = rows[: query.limit]
        ids = [row.id for row in page]
        datasets = await self._counts(DojoSuiteDataset.suite_id, ids)
        studies = await self._counts(DojoStudy.suite_id, ids)
        return SuiteListPage(
            items=[
                _suite_summary(row, datasets.get(row.id, 0), studies.get(row.id, 0))
                for row in page
            ],
            next_offset=query.offset + query.limit if len(rows) > query.limit else None,
        )

    async def get_suite(self, suite_id: str) -> SuiteView:
        row = await self._suite(suite_id)
        datasets = await self._datasets(suite_id)
        dataset_ids = [item.id for item in datasets]
        labels = await self._labels(dataset_ids)
        names = await self._series_names(dataset_ids)
        studies = (
            await self.session.scalars(
                select(DojoStudy)
                .where(DojoStudy.suite_id == suite_id)
                .order_by(DojoStudy.created_at.desc(), DojoStudy.id)
                .limit(MAX_SUITE_STUDIES)
            )
        ).all()
        # The overview ranks what has finished, so it works out the scores
        # a study has not been read for yet, for a few seconds at most.
        summaries = await self._summaries(studies, len(datasets), calculate=True)
        total = await self.session.scalar(
            select(func.count()).where(DojoStudy.suite_id == suite_id)
        )
        return SuiteView(
            **_suite_summary(row, len(datasets), total or 0).model_dump(),
            items=[
                SuiteDataset(
                    dataset_id=item.id,
                    name=item.name,
                    origin=cast(DatasetOrigin, item.origin),
                    series_names=names.get(item.id, []),
                    point_count=item.point_count,
                    labels=len(labels.get(item.id, [])),
                )
                for item in datasets
            ],
            leaderboard=sorted(
                (item for item in summaries if item.complete), key=_rank
            ),
            unfinished=[item for item in summaries if not item.complete],
        )

    async def change_suite(
        self, suite_id: str, change: SuiteChange, caller: User | Agent | None = None
    ) -> SuiteView:
        await require_application_writes(self.session)
        row = await self._suite(suite_id)
        _require_made_by(caller, row.created_by_agent_id, "suites")
        if change.name is not None:
            row.name = change.name.strip()
        if change.description is not None:
            row.description = change.description.strip()
        await self.session.commit()
        return await self.get_suite(suite_id)

    async def review_suite(self, suite_id: str, *, reviewed_by: int) -> SuiteView:
        """A member vouches for a suite a key made."""
        await require_application_writes(self.session)
        row = await self._suite(suite_id)
        if row.reviewed_at is None:
            row.reviewed_by = reviewed_by
            row.reviewed_at = datetime.now(UTC)
            await self.session.commit()
        return await self.get_suite(suite_id)

    async def remove_suite(
        self, suite_id: str, caller: User | Agent | None = None
    ) -> None:
        """Delete a suite with its studies and their runs."""
        await require_application_writes(self.session)
        row = await self._suite(suite_id)
        _require_made_by(caller, row.created_by_agent_id, "suites")
        studies = (
            await self.session.scalars(
                select(DojoStudy).where(DojoStudy.suite_id == suite_id)
            )
        ).all()
        for study in studies:
            _require_made_by(caller, study.created_by_agent_id, "studies")
        await self._delete_studies([study.id for study in studies], caller)
        await self.session.delete(row)
        await self.session.commit()

    # Studies

    async def create_study(
        self,
        request: StudyCreate,
        *,
        created_by: int | None,
        created_by_agent: Agent | None = None,
    ) -> StudyView:
        await require_application_writes(self.session)
        suite = await self._suite(request.suite_id)
        datasets = await self._datasets(suite.id)
        compiled = compile_design(request.definition)
        slots = compiled.definition.input_slots
        unknown = sorted(set(request.bindings) - {slot.id for slot in slots})
        if unknown:
            raise ValidationError(
                f"The design has no input {', '.join(map(repr, unknown))}"
            )
        bound: list[tuple[DojoDataset, dict[str, DojoSeries]]] = []
        problems = []
        for dataset in datasets:
            series = list((await dataset_series(self.session, dataset.id)).values())
            chosen, missing = _bind(slots, series, request.bindings)
            if missing:
                problems.append(f"{dataset.name!r} has no series for {missing}")
            bound.append((dataset, chosen))
        if problems:
            raise ValidationError(
                "Name a series for each input in `bindings`: "
                + "; ".join(problems[:5])
                + (f"; and {len(problems) - 5} more" if len(problems) > 5 else "")
            )
        runs = DojoRuns(self.session)
        await runs.require_queue_room()
        name = request.name.strip() or suite.name
        study = DojoStudy(
            id=str(uuid4()),
            suite_id=suite.id,
            name=name,
            config={
                "definition": compiled.definition.model_dump(mode="json"),
                "bindings": request.bindings,
                "alignment": request.alignment.model_dump(mode="json"),
                **(
                    {"created_by_agent": created_by_agent.name}
                    if created_by_agent
                    else {}
                ),
            },
            created_by=created_by,
            created_by_agent_id=created_by_agent.id if created_by_agent else None,
        )
        self.session.add(study)
        await self.session.flush()
        for dataset, chosen in bound:
            runs.queue(
                dataset,
                compiled,
                chosen,
                name=name[:120],
                alignment=request.alignment,
                created_by=created_by,
                created_by_agent=created_by_agent,
                study_id=study.id,
            )
        await self.session.commit()
        return await self.get_study(study.id)

    async def list_studies(
        self, query: StudyListQuery, caller: User | Agent | None = None
    ) -> StudyListPage:
        statement = select(DojoStudy)
        if query.suite_id is not None:
            statement = statement.where(DojoStudy.suite_id == query.suite_id)
        if query.mine and caller is not None:
            statement = statement.where(
                made_by(caller, DojoStudy.created_by, DojoStudy.created_by_agent_id)
            )
        rows = (
            await self.session.scalars(
                statement.order_by(DojoStudy.created_at.desc(), DojoStudy.id)
                .offset(query.offset)
                .limit(query.limit + 1)
            )
        ).all()
        page = rows[: query.limit]
        sizes = await self._counts(
            DojoSuiteDataset.suite_id, list({row.suite_id for row in page})
        )
        summaries = []
        for row in page:
            summaries.extend(await self._summaries([row], sizes.get(row.suite_id, 0)))
        return StudyListPage(
            items=summaries,
            next_offset=query.offset + query.limit if len(rows) > query.limit else None,
        )

    async def get_study(self, study_id: str, *, calculate: bool = False) -> StudyView:
        """The study with each run's metrics. With ``calculate``, the metrics
        of finished runs are calculated first, for a few seconds at most."""
        study = await self._study(study_id)
        runs = await self._runs([study.id])
        labels = await self._labels(list({run.dataset_id for run in runs}))
        found = await self._metrics(runs, labels, calculate=calculate)
        size = len(await self._datasets(study.suite_id))
        names = await self._dataset_names([run.dataset_id for run in runs])
        return StudyView(
            **_study_summary(study, runs, found, size).model_dump(),
            definition=study.config["definition"],
            bindings=study.config.get("bindings", {}),
            alignment=RunAlignment.model_validate(study.config["alignment"]),
            items=[
                StudyItem(
                    dataset_id=run.dataset_id,
                    dataset_name=names.get(run.dataset_id, run.dataset_id),
                    run_id=run.id,
                    status=cast(RunStatus, run.status),
                    error=run.error,
                    metrics=found[run.id],
                )
                for run in runs
            ],
        )

    async def compare_studies(
        self, suite_id: str, query: StudyComparisonQuery
    ) -> StudyComparison:
        """Two studies of the suite, dataset by dataset, with a paired test."""
        await self._suite(suite_id)
        studies = [
            await self._study(query.baseline),
            await self._study(query.challenger),
        ]
        elsewhere = [item.id for item in studies if item.suite_id != suite_id]
        if elsewhere:
            raise ValidationError(
                f"Compare studies of one suite; {', '.join(map(repr, elsewhere))} "
                "ran on another"
            )
        datasets = await self._datasets(suite_id)
        runs = await self._runs([item.id for item in studies])
        labels = await self._labels([item.id for item in datasets])
        found = await self._metrics(runs, labels, calculate=True)
        values: dict[str, dict[str, float | None]] = defaultdict(dict)
        for run in runs:
            if run.study_id is not None:
                values[run.study_id][run.dataset_id] = _value(
                    found.get(run.id), query.metric
                )
        pairs = []
        for dataset in datasets:
            before = values[query.baseline].get(dataset.id)
            after = values[query.challenger].get(dataset.id)
            pairs.append(
                PairedDataset(
                    dataset_id=dataset.id,
                    dataset_name=dataset.name,
                    baseline=before,
                    challenger=after,
                    delta=None if before is None or after is None else after - before,
                )
            )
        deltas = [item.delta for item in pairs if item.delta is not None]
        return StudyComparison(
            suite_id=suite_id,
            metric=query.metric,
            baseline=query.baseline,
            challenger=query.challenger,
            datasets=pairs,
            compared=len(deltas),
            wins=sum(1 for item in deltas if item > 0),
            losses=sum(1 for item in deltas if item < 0),
            ties=sum(1 for item in deltas if item == 0),
            mean_delta=mean(deltas) if deltas else None,
            median_delta=median(deltas) if deltas else None,
            p_value=wilcoxon(deltas),
        )

    async def cancel_study(
        self, study_id: str, caller: User | Agent | None = None
    ) -> StudyView:
        """Waiting runs end at once, running ones at the worker's next beat."""
        await require_application_writes(self.session)
        study = await self._study(study_id)
        _require_made_by(caller, study.created_by_agent_id, "studies")
        runs = (
            await self.session.scalars(
                select(DojoRun)
                .where(DojoRun.study_id == study.id, DojoRun.status.in_(ACTIVE))
                .with_for_update()
            )
        ).all()
        if not runs:
            raise ConflictError("No run of the study waits or runs")
        now = datetime.now(UTC)
        for run in runs:
            if run.status == "queued":
                run.status = "cancelled"
                run.finished_at = now
            else:
                run.cancel_requested = True
        await self.session.commit()
        return await self.get_study(study.id)

    async def remove_study(
        self, study_id: str, caller: User | Agent | None = None
    ) -> None:
        """Delete a study and its runs, once none of them waits or runs."""
        await require_application_writes(self.session)
        study = await self._study(study_id)
        _require_made_by(caller, study.created_by_agent_id, "studies")
        await self._delete_studies([study.id], caller)
        await self.session.commit()

    # Helpers

    async def _metrics(
        self,
        runs: Sequence[DojoRun],
        labels: dict[str, list[DojoLabel]],
        *,
        calculate: bool,
    ) -> dict[str, RunMetrics | None]:
        metrics = DojoMetrics(self.session)
        found = {
            run.id: metrics.cached(run, labels.get(run.dataset_id, [])) for run in runs
        }
        if not calculate:
            return found
        started = time.monotonic()
        for run in runs:
            if run.status != "succeeded" or found[run.id] is not None:
                continue
            if time.monotonic() - started > CALCULATE_SECONDS:
                break
            found[run.id] = await metrics.calculate(run, labels.get(run.dataset_id, []))
            if found[run.id] is None:
                break
        return found

    async def _delete_studies(
        self, study_ids: Sequence[str], caller: User | Agent | None
    ) -> None:
        if not study_ids:
            return
        runs = (
            await self.session.scalars(
                select(DojoRun).where(DojoRun.study_id.in_(study_ids)).with_for_update()
            )
        ).all()
        if any(run.status in ACTIVE for run in runs):
            raise ConflictError("Cancel the study before deleting it")
        run_ids = [run.id for run in runs]
        await require_no_evidence(self.session, run_ids)
        # Results carry no foreign key (see DojoRunResult).
        await self.session.execute(
            delete(DojoRunResult).where(DojoRunResult.run_id.in_(run_ids))
        )
        await self.session.execute(delete(DojoRun).where(DojoRun.id.in_(run_ids)))
        await self.session.execute(delete(DojoStudy).where(DojoStudy.id.in_(study_ids)))
        if isinstance(caller, Agent):
            log_security_event(
                "dojo_studies_deleted_by_agent",
                caller.name,
                {"study_ids": list(study_ids), "runs": len(run_ids)},
            )

    async def _summaries(
        self, studies: Sequence[DojoStudy], size: int, *, calculate: bool = False
    ) -> list[StudySummary]:
        runs = await self._runs([study.id for study in studies])
        labels = await self._labels(list({run.dataset_id for run in runs}))
        found = await self._metrics(runs, labels, calculate=calculate)
        by_study: dict[str, list[DojoRun]] = defaultdict(list)
        for run in runs:
            by_study[run.study_id or ""].append(run)
        return [
            _study_summary(study, by_study[study.id], found, size) for study in studies
        ]

    async def _runs(self, study_ids: Sequence[str]) -> list[DojoRun]:
        if not study_ids:
            return []
        return list(
            (
                await self.session.scalars(
                    # One transaction queues a study, so its runs share a
                    # creation time: the suite's order is the one to keep.
                    select(DojoRun)
                    .join(DojoStudy, DojoStudy.id == DojoRun.study_id)
                    .outerjoin(
                        DojoSuiteDataset,
                        (DojoSuiteDataset.suite_id == DojoStudy.suite_id)
                        & (DojoSuiteDataset.dataset_id == DojoRun.dataset_id),
                    )
                    .where(DojoRun.study_id.in_(study_ids))
                    .order_by(DojoSuiteDataset.position, DojoRun.id)
                )
            ).all()
        )

    async def _labels(self, dataset_ids: Sequence[str]) -> dict[str, list[DojoLabel]]:
        found: dict[str, list[DojoLabel]] = defaultdict(list)
        if not dataset_ids:
            return found
        for label in (
            await self.session.scalars(
                select(DojoLabel)
                .where(DojoLabel.dataset_id.in_(dataset_ids))
                .order_by(DojoLabel.start_at, DojoLabel.id)
            )
        ).all():
            found[label.dataset_id].append(label)
        return found

    async def _series_names(self, dataset_ids: Sequence[str]) -> dict[str, list[str]]:
        found: dict[str, list[str]] = defaultdict(list)
        for dataset_id, name in (
            await self.session.execute(
                select(DojoSeries.dataset_id, DojoSeries.name)
                .where(DojoSeries.dataset_id.in_(dataset_ids))
                .order_by(DojoSeries.position)
            )
        ).all():
            found[dataset_id].append(name)
        return found

    async def _dataset_names(self, dataset_ids: Sequence[str]) -> dict[str, str]:
        return dict(
            (
                await self.session.execute(
                    select(DojoDataset.id, DojoDataset.name).where(
                        DojoDataset.id.in_(dataset_ids)
                    )
                )
            ).all()
        )

    async def _datasets(self, suite_id: str) -> list[DojoDataset]:
        return list(
            (
                await self.session.scalars(
                    select(DojoDataset)
                    .join(
                        DojoSuiteDataset, DojoSuiteDataset.dataset_id == DojoDataset.id
                    )
                    .where(DojoSuiteDataset.suite_id == suite_id)
                    .order_by(DojoSuiteDataset.position)
                )
            ).all()
        )

    async def _counts(self, column, ids: Sequence[str]) -> dict[str, int]:
        if not ids:
            return {}
        return dict(
            (
                await self.session.execute(
                    select(column, func.count()).where(column.in_(ids)).group_by(column)
                )
            ).all()
        )

    async def _require_datasets(self, dataset_ids: Sequence[str]) -> None:
        known = set(
            (
                await self.session.scalars(
                    select(DojoDataset.id).where(DojoDataset.id.in_(dataset_ids))
                )
            ).all()
        )
        missing = [item for item in dataset_ids if item not in known]
        if missing:
            raise NotFoundError(f"No dataset {', '.join(map(repr, missing[:5]))}")

    async def _suite(self, suite_id: str) -> DojoSuite:
        row = await self.session.get(DojoSuite, suite_id)
        if row is None:
            raise NotFoundError("Suite not found")
        return row

    async def _study(self, study_id: str) -> DojoStudy:
        row = await self.session.get(DojoStudy, study_id)
        if row is None:
            raise NotFoundError("Study not found")
        return row


def _bind(slots, series: list[DojoSeries], bindings: dict[str, str]):
    """Each slot's series in one dataset, and the slots none fits."""
    by_name = {item.name: item for item in series}
    chosen: dict[str, DojoSeries] = {}
    missing = []
    for slot in slots:
        name = bindings.get(slot.id)
        if name is not None:
            item = by_name.get(name)
        elif len(slots) == 1 and len(series) == 1:
            item = series[0]
        else:
            item = by_name.get(slot.id) or by_name.get(slot.label)
        if item is None:
            missing.append(repr(slot.id))
        else:
            chosen[slot.id] = item
    return chosen, ", ".join(missing)


def totals(found: Sequence[RunMetrics]) -> StudyTotals:
    """Add up the metrics of a study's runs."""

    def average(values):
        values = [value for value in values if value is not None]
        return (mean(values) if values else None), len(values)

    scores = [item.scores for item in found if item.scores is not None]
    pr_auc, pr_auc_runs = average(item.pr_auc for item in scores)
    vus_pr, vus_pr_runs = average(item.vus_pr for item in scores)
    auroc, auroc_runs = average(item.auroc for item in scores)
    top1 = [item.top1_hit for item in scores if item.top1_hit is not None]
    scored = sum(item.labels_scored for item in found)
    detected = sum(item.labels_detected for item in found)
    rates = [
        item.false_alarms_per_day
        for item in found
        if item.false_alarms_per_day is not None
    ]
    return StudyTotals(
        runs_scored=len(found),
        labels_scored=scored,
        labels_detected=detected,
        detection_rate=detected / scored if scored else None,
        median_false_alarms_per_day=median(rates) if rates else None,
        pr_auc=pr_auc,
        pr_auc_runs=pr_auc_runs,
        vus_pr=vus_pr,
        vus_pr_runs=vus_pr_runs,
        auroc=auroc,
        auroc_runs=auroc_runs,
        top1_hits=sum(top1),
        top1_runs=len(top1),
    )


def wilcoxon(deltas: Sequence[float]) -> float | None:
    """Two-sided p-value of the Wilcoxon signed-rank test, zeros dropped.

    Exact from the distribution of rank sums when no two differences tie,
    otherwise the normal approximation with the tie correction.
    """
    values = [item for item in deltas if item != 0]
    n = len(values)
    if n < 2:
        return None
    order = sorted(range(n), key=lambda index: abs(values[index]))
    ranks = [0.0] * n
    groups = []
    start = 0
    for end in range(1, n + 1):
        if end == n or abs(values[order[end]]) != abs(values[order[start]]):
            rank = (start + end + 1) / 2
            for index in order[start:end]:
                ranks[index] = rank
            groups.append(end - start)
            start = end
    positive = sum(rank for rank, value in zip(ranks, values, strict=True) if value > 0)
    total = n * (n + 1) / 2
    statistic = min(positive, total - positive)
    if all(size == 1 for size in groups):
        # Ways each rank sum arises when every sign is a coin toss.
        counts = [1] + [0] * int(total)
        for rank in range(1, n + 1):
            for value in range(int(total), rank - 1, -1):
                counts[value] += counts[value - rank]
        tail = sum(counts[: int(statistic) + 1]) / 2**n
        return min(1.0, 2 * tail)
    expected = total / 2
    variance = (
        n * (n + 1) * (2 * n + 1) / 24 - sum(size**3 - size for size in groups) / 48
    )
    if variance <= 0:
        return None
    z = (statistic - expected) / math.sqrt(variance)
    return min(1.0, math.erfc(abs(z) / math.sqrt(2)))


def _value(metrics: RunMetrics | None, metric: StudyMetric) -> float | None:
    if metrics is None:
        return None
    if metric == "detection_rate":
        return metrics.detection_rate
    scores = metrics.scores
    return None if scores is None else getattr(scores, metric)


def _study_summary(
    study: DojoStudy,
    runs: Sequence[DojoRun],
    found: dict[str, RunMetrics | None],
    size: int,
) -> StudySummary:
    metrics = [item for run in runs if (item := found.get(run.id)) is not None]
    return StudySummary(
        id=study.id,
        suite_id=study.suite_id,
        name=study.name,
        strategy=result_kind(study.config["definition"]),
        runs=dict(Counter(run.status for run in runs)),
        complete=size > 0 and len(runs) == size and len(metrics) == size,
        totals=totals(metrics),
        metrics_pending=sum(
            1 for run in runs if run.status == "succeeded" and found.get(run.id) is None
        ),
        created_by=study.created_by,
        created_by_agent=study.config.get("created_by_agent"),
        created_at=study.created_at,
    )


def _suite_summary(row: DojoSuite, datasets: int, studies: int) -> SuiteSummary:
    return SuiteSummary(
        id=row.id,
        name=row.name,
        description=row.description,
        derived_from=row.derived_from,
        datasets=datasets,
        studies=studies,
        created_by=row.created_by,
        created_by_agent=row.created_by_agent,
        reviewed=row.reviewed_at is not None,
        created_at=row.created_at,
    )


def _rank(summary: StudySummary):
    item = summary.totals
    return (
        item.vus_pr is None,
        -(item.vus_pr or 0.0),
        -(item.pr_auc or 0.0),
        -(item.detection_rate or 0.0),
        -summary.created_at.timestamp(),
    )


def _require_made_by(caller: User | Agent | None, agent_id: int | None, what: str):
    if isinstance(caller, Agent) and agent_id != caller.id:
        raise ForbiddenError(f"A key changes and deletes only the {what} it made")


def _draw_faults(
    draw: random.Random,
    request: FaultSuiteCreate,
    start: datetime,
    end: datetime,
    targets: Sequence,
    spreads: dict[str, float | None],
    taken: Sequence[tuple[datetime, datetime]],
) -> list[Fault]:
    """Faults for one copy: after the clean start, apart from each other and
    from the labels, of the given kinds on the given series."""
    span = end - start
    values = max(item.point_count for item in targets)
    shortest = max(span * FAULT_SHARE[0], span * FAULT_VALUES / max(values - 1, 1))
    longest = max(span * FAULT_SHARE[1], shortest)
    earliest = start + span * request.clean_share
    busy = list(taken)
    faults: list[Fault] = []
    for _ in range(request.faults_per_copy * FAULT_ATTEMPTS):
        if len(faults) == request.faults_per_copy:
            break
        length = shortest + (longest - shortest) * draw.random()
        room = end - length - earliest
        if room.total_seconds() <= 0:
            break
        begin = earliest + room * draw.random()
        finish = begin + length
        # A fault keeps its own length of distance to the others and the labels.
        if any(begin < b + length and finish + length > a for a, b in busy):
            continue
        kind = draw.choice(request.kinds)
        series = draw.choice(list(targets))
        size = None
        if kind in ("step", "drift"):
            spread = spreads.get(series.id) or 1.0
            sigmas = draw.uniform(*FAULT_SIGMAS)
            size = draw.choice((-1.0, 1.0)) * sigmas * spread
        faults.append(
            Fault(
                kind=kind,
                series_id=series.id,
                start_at=begin,
                end_at=finish,
                size=size,
            )
        )
        busy.append((begin, finish))
    if not faults:
        raise ValidationError(
            "The dataset has no room for faults after its clean start and "
            "outside its labels; lower clean_share or remove labels"
        )
    return sorted(faults, key=lambda item: item.start_at)
