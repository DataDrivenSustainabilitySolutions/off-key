"""Dojo datasets and runs: replay detection designs over stored time series.

Open to members whose role grants `use_dojo`, reads included.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from off_key_core.auth.agents import OPEN_TO_AGENTS
from off_key_core.auth.permissions import Permission
from off_key_core.db.models import Agent, User
from off_key_core.schemas.dojo import (
    MAX_UPLOAD_BYTES,
    BenchmarkImport,
    BenchmarkImportResult,
    BenchmarkListPage,
    BenchmarkListQuery,
    Comparison,
    ComparisonQuery,
    CsvImportQuery,
    DatasetChange,
    DatasetFromHistory,
    DatasetListPage,
    DatasetListQuery,
    DatasetPointsPage,
    DatasetPointsQuery,
    DatasetProfile,
    DatasetView,
    DatasetWithFaults,
    DojoDeletion,
    DojoDeletionResult,
    FaultSuiteCreate,
    LabelBatch,
    LabelChange,
    LabelCreate,
    LabelList,
    LabelRule,
    LabelSuggestionList,
    LabelSuggestionQuery,
    LabelView,
    MethodComparison,
    PendingLabelAccept,
    PendingLabelDismiss,
    PendingLabelList,
    PendingLabelProposal,
    PendingLabelsMade,
    RunCreate,
    RunListPage,
    RunListQuery,
    RunMetrics,
    RunOutline,
    RunOutlineQuery,
    RunPromote,
    RunPromotion,
    RunResultsPage,
    RunResultsQuery,
    RunSteps,
    RunView,
    SeriesProfile,
    StudyComparison,
    StudyComparisonQuery,
    StudyCreate,
    StudyListPage,
    StudyListQuery,
    StudyView,
    SuiteChange,
    SuiteCreate,
    SuiteListPage,
    SuiteListQuery,
    SuiteView,
)
from off_key_tactic_middleware.services.dojo.benchmarks import DojoBenchmarks
from off_key_tactic_middleware.services.dojo.datasets import DojoDatasets
from off_key_tactic_middleware.services.dojo.deletions import DojoDeletions
from off_key_tactic_middleware.services.dojo.labels import DojoLabels
from off_key_tactic_middleware.services.dojo.metrics import DojoMetrics
from off_key_tactic_middleware.services.dojo.pending_labels import DojoPendingLabels
from off_key_tactic_middleware.services.dojo.runs import DojoRuns
from off_key_tactic_middleware.services.dojo.suites import DojoSuites

from ...providers import (
    get_dojo_benchmarks,
    get_dojo_datasets,
    get_dojo_deletions,
    get_dojo_labels,
    get_dojo_metrics,
    get_dojo_pending_labels,
    get_dojo_runs,
    get_dojo_suites,
)
from ..access import agent_of, caller_key, member_id, require_permission
from ..errors import DomainErrorRoute
from ..rate_limiter import client_ip, limiter

use_dojo = require_permission(Permission.use_dojo)
manage_monitors = require_permission(Permission.manage_monitors)


async def member_scope(request: Request, caller: User | Agent = Depends(use_dojo)):
    request.state.dojo_member_id = caller_key(caller)


def member_key(request: Request) -> str:
    if getattr(request.state, "demo_guest", False):
        return f"demo:{client_ip(request)}"
    return request.state.dojo_member_id


router = APIRouter(dependencies=[Depends(member_scope)], route_class=DomainErrorRoute)
read_limit = limiter.shared_limit("240/minute", scope="dojo-reads", key_func=member_key)
write_limit = limiter.shared_limit(
    "30/minute", scope="dojo-writes", key_func=member_key
)
upload_limit = limiter.shared_limit(
    "6/minute", scope="dojo-uploads", key_func=member_key
)


@router.get("/datasets", response_model=DatasetListPage, openapi_extra=OPEN_TO_AGENTS)
@read_limit
async def list_dojo_datasets(
    request: Request,
    query: Annotated[DatasetListQuery, Query()],
    caller: User | Agent = Depends(use_dojo),
    datasets: DojoDatasets = Depends(get_dojo_datasets),
):
    """Datasets in the Dojo, newest first, with their size and time span.

    `mine=true` keeps the datasets the caller made: a key's own, or the
    member's own.
    """
    return await datasets.list(query, caller)


@router.post(
    "/datasets/csv",
    response_model=DatasetView,
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "description": "The CSV file itself, UTF-8, at most 100 MB.",
            "content": {"text/csv": {"schema": {"type": "string"}}},
        }
    },
)
@upload_limit
async def import_dojo_csv(
    request: Request,
    query: Annotated[CsvImportQuery, Query()],
    user: User = Depends(use_dojo),
    datasets: DojoDatasets = Depends(get_dojo_datasets),
):
    """Create a dataset from a CSV sent as the request body.

    `layout=wide` (default) reads one timestamp column, the first unless
    `timestamp_column` names another, and one series per remaining column.
    `layout=long` reads one value per row from the `series`, `timestamp` and
    `value` columns. Timestamps are ISO 8601 or Unix epoch seconds or
    milliseconds; without a zone they are UTC. The delimiter (`,` `;` tab `|`)
    is detected from the header, and with `;` or tab a decimal comma is
    accepted. Empty cells are skipped. Limits: 64 series, 5,000,000 values.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Upload at most 100 MB of CSV")
    body = await request.body()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Upload at most 100 MB of CSV")
    return await datasets.import_csv(body, query, created_by=user.id)


@router.post(
    "/datasets/history",
    response_model=DatasetView,
    status_code=201,
    openapi_extra=OPEN_TO_AGENTS,
)
@write_limit
async def import_dojo_history(
    request: Request,
    change: DatasetFromHistory,
    caller: User | Agent = Depends(use_dojo),
    datasets: DojoDatasets = Depends(get_dojo_datasets),
):
    """Create a dataset by copying recorded readings for one time window.

    `reading_ids` are reading ids from `GET /v1/catalogue`. Each becomes
    one series named after the reading. Without `start`, everything still
    stored up to `end` is copied. The copy is frozen: later retention or
    catalogue edits do not change it.
    """
    return await datasets.import_history(
        change, created_by=member_id(caller), created_by_agent=agent_of(caller)
    )


@router.get(
    "/benchmarks", response_model=BenchmarkListPage, openapi_extra=OPEN_TO_AGENTS
)
@read_limit
async def list_dojo_benchmarks(
    request: Request,
    query: Annotated[BenchmarkListQuery, Query()],
    caller: User | Agent = Depends(use_dojo),
    benchmarks: DojoBenchmarks = Depends(get_dojo_benchmarks),
):
    """Series of public benchmark collections the Dojo can import.

    Today this is the UCR Time Series Anomaly Archive: 250 univariate series,
    each with one labelled anomaly after an anomaly-free training part.
    `text` matches every word against the number, name, domain and variant;
    `dataset_id` names the dataset a series was imported as. Cite the
    collection's `citation` when you report results.
    """
    return await benchmarks.list(query)


@router.post(
    "/benchmarks/import",
    response_model=BenchmarkImportResult,
    status_code=201,
    openapi_extra=OPEN_TO_AGENTS,
)
@upload_limit
async def import_dojo_benchmarks(
    request: Request,
    change: BenchmarkImport,
    caller: User | Agent = Depends(use_dojo),
    benchmarks: DojoBenchmarks = Depends(get_dojo_benchmarks),
):
    """Import benchmark series, each as a dataset with its anomaly as a label.

    The file is downloaded from the collection's pinned mirror and checked
    against its recorded SHA-256. Value i is stored at 2021-01-01T00:00:00Z
    plus i seconds. The dataset's `source` keeps the series, the training
    part (`train_points`, `train_end_at`) and the citation. A series imported
    before returns its existing dataset.
    """
    return await benchmarks.import_series(
        change, created_by=member_id(caller), created_by_agent=agent_of(caller)
    )


@router.post(
    "/datasets/{dataset_id}/faults",
    response_model=DatasetView,
    status_code=201,
    openapi_extra=OPEN_TO_AGENTS,
)
@write_limit
async def inject_dojo_faults(
    request: Request,
    dataset_id: str,
    change: DatasetWithFaults,
    caller: User | Agent = Depends(use_dojo),
    datasets: DojoDatasets = Depends(get_dojo_datasets),
):
    """Copy a dataset with faults written in, to test what a design catches.

    Each fault is a step, a drift, a frozen value or a gap on one series
    between two times, and becomes a label of the copy, so a run's metrics
    say how many the design detected and how late. The copy keeps the
    dataset's own labels; faults may not overlap them or each other.
    """
    return await datasets.inject_faults(
        dataset_id,
        change,
        created_by=member_id(caller),
        created_by_agent=agent_of(caller),
    )


@router.get(
    "/datasets/{dataset_id}", response_model=DatasetView, openapi_extra=OPEN_TO_AGENTS
)
@read_limit
async def get_dojo_dataset(
    request: Request,
    dataset_id: str,
    datasets: DojoDatasets = Depends(get_dojo_datasets),
):
    """One dataset with its series, their units and time spans."""
    return await datasets.get(dataset_id)


@router.patch("/datasets/{dataset_id}", response_model=DatasetView)
@write_limit
async def change_dojo_dataset(
    request: Request,
    dataset_id: str,
    change: DatasetChange,
    datasets: DojoDatasets = Depends(get_dojo_datasets),
):
    """Rename a dataset or change its description."""
    return await datasets.change(dataset_id, change)


@router.delete("/datasets/{dataset_id}", status_code=204, openapi_extra=OPEN_TO_AGENTS)
@write_limit
async def delete_dojo_dataset(
    request: Request,
    dataset_id: str,
    caller: User | Agent = Depends(use_dojo),
    datasets: DojoDatasets = Depends(get_dojo_datasets),
):
    """Delete a dataset and all its values and runs. This cannot be undone.

    A key deletes only a dataset it made, holding only runs it queued, and none
    of them the test of a proposal that waits or was accepted or of a monitor;
    others answer 403 or 409.
    """
    await datasets.remove(dataset_id, caller)
    return Response(status_code=204)


@router.post(
    "/deletions", response_model=DojoDeletionResult, openapi_extra=OPEN_TO_AGENTS
)
@write_limit
async def delete_dojo_items(
    request: Request,
    body: DojoDeletion,
    caller: User | Agent = Depends(use_dojo),
    deletions: DojoDeletions = Depends(get_dojo_deletions),
):
    """Delete several suites, studies and datasets at once. This cannot be undone.

    Suites go first, then studies, then datasets. Each item follows the rules
    of its own delete, and one that is refused is named with its reason while
    the others are deleted.
    """
    return await deletions.remove(body, caller)


@router.get(
    "/datasets/{dataset_id}/series/{series_id}/points",
    response_model=DatasetPointsPage,
    openapi_extra=OPEN_TO_AGENTS,
)
@read_limit
async def list_dojo_points(
    request: Request,
    dataset_id: str,
    series_id: str,
    query: Annotated[DatasetPointsQuery, Query()],
    datasets: DojoDatasets = Depends(get_dojo_datasets),
):
    """The values of one series in time order, a page at a time.

    Pass the returned `next_after` as `after` to continue; it is null on the
    last page.
    """
    return await datasets.points(dataset_id, series_id, query)


@router.get(
    "/datasets/{dataset_id}/profile",
    response_model=DatasetProfile,
    openapi_extra=OPEN_TO_AGENTS,
)
@read_limit
async def profile_dojo_dataset(
    request: Request,
    dataset_id: str,
    datasets: DojoDatasets = Depends(get_dojo_datasets),
):
    """A whole dataset at a glance: each series' course, values, level change
    and cycles, which series move together, and where the labels lie."""
    return await datasets.profile_dataset(dataset_id)


@router.get(
    "/datasets/{dataset_id}/series/{series_id}/profile",
    response_model=SeriesProfile,
    openapi_extra=OPEN_TO_AGENTS,
)
@read_limit
async def profile_dojo_series(
    request: Request,
    dataset_id: str,
    series_id: str,
    datasets: DojoDatasets = Depends(get_dojo_datasets),
):
    """One series in full: its values, course and level change, and how it
    relates to its own past: autocorrelation, suggested lags and cycles."""
    return await datasets.profile(dataset_id, series_id)


@router.get(
    "/datasets/{dataset_id}/labels",
    response_model=LabelList,
    openapi_extra=OPEN_TO_AGENTS,
)
@read_limit
async def list_dojo_labels(
    request: Request,
    dataset_id: str,
    labels: DojoLabels = Depends(get_dojo_labels),
):
    """The dataset's labels, each a time interval with a known problem,
    ordered by start."""
    return await labels.list(dataset_id)


@router.get(
    "/datasets/{dataset_id}/label-suggestions",
    response_model=LabelSuggestionList,
    openapi_extra=OPEN_TO_AGENTS,
)
@read_limit
async def suggest_dojo_labels(
    request: Request,
    dataset_id: str,
    query: Annotated[LabelSuggestionQuery, Query()],
    labels: DojoLabels = Depends(get_dojo_labels),
):
    """Alarms live monitors recorded on the readings the dataset was copied
    from, inside its time span, as candidate labels.

    Alarms closer together than `gap_seconds` form one suggestion. Nothing is
    stored: add a suggestion with `POST .../labels`. An uploaded dataset has
    no recorded readings and gets none.
    """
    return await labels.suggestions(dataset_id, query)


@router.post("/datasets/{dataset_id}/labels", response_model=LabelView, status_code=201)
@write_limit
async def create_dojo_label(
    request: Request,
    dataset_id: str,
    label: LabelCreate,
    user: User = Depends(use_dojo),
    labels: DojoLabels = Depends(get_dojo_labels),
):
    """Mark a known problem from `start_at` to `end_at`.

    Labels of one dataset may touch but not overlap, and must overlap the
    dataset's time span. A dataset holds at most 500. Run metrics read the
    labels when asked, so adding one re-scores every finished run.
    """
    return await labels.create(dataset_id, label, created_by=user.id)


@router.post(
    "/datasets/{dataset_id}/labels/batch", response_model=LabelList, status_code=201
)
@write_limit
async def create_dojo_labels(
    request: Request,
    dataset_id: str,
    batch: LabelBatch,
    user: User = Depends(use_dojo),
    labels: DojoLabels = Depends(get_dojo_labels),
):
    """Add up to 200 labels at once, as one write.

    All of them are added, or none when one is refused: labels may not
    overlap each other or the dataset's labels, and a dataset holds at most
    500. Returns the new labels in the order given.
    """
    created = await labels.create_many(dataset_id, batch.labels, created_by=user.id)
    return LabelList(items=created)


@router.get(
    "/datasets/{dataset_id}/pending-labels",
    response_model=PendingLabelList,
    openapi_extra=OPEN_TO_AGENTS,
)
@read_limit
async def list_dojo_pending_labels(
    request: Request,
    dataset_id: str,
    pending: DojoPendingLabels = Depends(get_dojo_pending_labels),
):
    """Labels members and agents proposed, waiting for a member to add or
    dismiss them. They score no run until added."""
    return await pending.list(dataset_id)


@router.post(
    "/datasets/{dataset_id}/pending-labels",
    response_model=PendingLabelsMade,
    status_code=201,
    openapi_extra=OPEN_TO_AGENTS,
)
@write_limit
async def propose_dojo_labels(
    request: Request,
    dataset_id: str,
    proposal: PendingLabelProposal,
    caller: User | Agent = Depends(use_dojo),
    pending: DojoPendingLabels = Depends(get_dojo_pending_labels),
):
    """Propose up to 200 intervals as labels, for a member to review.

    Say in `rule` how they were chosen. Intervals that overlap a label are
    left out and counted in `skipped`. With `replace`, your own pending labels
    on the dataset are dismissed first; with no intervals, that withdraws them.
    """
    return await pending.propose(dataset_id, proposal, caller)


@router.post(
    "/datasets/{dataset_id}/pending-labels/by-rule",
    response_model=PendingLabelsMade,
    status_code=201,
    openapi_extra=OPEN_TO_AGENTS,
)
@write_limit
async def propose_dojo_labels_by_rule(
    request: Request,
    dataset_id: str,
    rule: LabelRule,
    caller: User | Agent = Depends(use_dojo),
    pending: DojoPendingLabels = Depends(get_dojo_pending_labels),
):
    """Propose a label for every interval where a condition over the
    dataset's series holds, for a member to review.

    The condition is written as a Gate step writes one, with the series by
    name. Up to 200 intervals are proposed, the earliest first; those that
    overlap a label are left out.
    """
    return await pending.propose_by_rule(dataset_id, rule, caller)


@router.post(
    "/datasets/{dataset_id}/pending-labels/accept",
    response_model=LabelList,
    status_code=201,
)
@write_limit
async def accept_dojo_pending_labels(
    request: Request,
    dataset_id: str,
    choice: PendingLabelAccept,
    user: User = Depends(use_dojo),
    pending: DojoPendingLabels = Depends(get_dojo_pending_labels),
):
    """Add pending labels as labels, each changed first if given.

    All of them are added, or none when one is refused, as with a batch of
    labels. A label keeps the rule that found it and the agent that proposed it.
    """
    added = await pending.accept(dataset_id, choice, created_by=user.id)
    return LabelList(items=added)


@router.post("/datasets/{dataset_id}/pending-labels/dismiss", status_code=204)
@write_limit
async def dismiss_dojo_pending_labels(
    request: Request,
    dataset_id: str,
    dismissal: PendingLabelDismiss,
    pending: DojoPendingLabels = Depends(get_dojo_pending_labels),
):
    """Dismiss pending labels without adding them."""
    await pending.dismiss(dataset_id, dismissal)
    return Response(status_code=204)


@router.patch("/datasets/{dataset_id}/labels/{label_id}", response_model=LabelView)
@write_limit
async def change_dojo_label(
    request: Request,
    dataset_id: str,
    label_id: str,
    change: LabelChange,
    labels: DojoLabels = Depends(get_dojo_labels),
):
    """Move a label's start or end, or change its note."""
    return await labels.change(dataset_id, label_id, change)


@router.delete("/datasets/{dataset_id}/labels/{label_id}", status_code=204)
@write_limit
async def delete_dojo_label(
    request: Request,
    dataset_id: str,
    label_id: str,
    labels: DojoLabels = Depends(get_dojo_labels),
):
    """Delete a label."""
    await labels.remove(dataset_id, label_id)
    return Response(status_code=204)


@router.get(
    "/datasets/{dataset_id}/comparison",
    response_model=Comparison,
    openapi_extra=OPEN_TO_AGENTS,
)
@read_limit
async def compare_dojo_runs(
    request: Request,
    dataset_id: str,
    query: Annotated[ComparisonQuery, Query()],
    metrics: DojoMetrics = Depends(get_dojo_metrics),
):
    """Up to six finished runs of the dataset, scored against its labels.

    Repeat `run_ids` for each run, for example
    `?run_ids=a&run_ids=b`. Each run carries the metrics of
    `GET /v1/dojo/runs/{run_id}/metrics`, and `labels` lists the intervals
    they were scored against.
    """
    return await metrics.compare(dataset_id, query)


@router.get("/runs", response_model=RunListPage, openapi_extra=OPEN_TO_AGENTS)
@read_limit
async def list_dojo_runs(
    request: Request,
    query: Annotated[RunListQuery, Query()],
    caller: User | Agent = Depends(use_dojo),
    runs: DojoRuns = Depends(get_dojo_runs),
):
    """Runs, newest first, optionally of one dataset or in one status.

    `mine=true` keeps the runs the caller queued: a key's own, or the
    member's own.
    """
    return await runs.list(query, caller)


@router.post(
    "/runs", response_model=RunView, status_code=201, openapi_extra=OPEN_TO_AGENTS
)
@write_limit
async def create_dojo_run(
    request: Request,
    run: RunCreate,
    caller: User | Agent = Depends(use_dojo),
    runs: DojoRuns = Depends(get_dojo_runs),
):
    """Queue a replay of one design over one dataset.

    `definition` is a design as the pipeline library stores it; `bindings`
    maps each of its input slot ids to a series id of the dataset. The design
    is compiled and bound now, so errors in it are refused here. The run then
    waits for a Dojo worker; poll `GET /v1/dojo/runs/{run_id}` for `status`
    and `points_read` of `points_total`. Points are replayed in time order
    through the same alignment and detector code as a live monitor, with the
    data's own timestamps as the clock. At most 20 runs wait or run at once.

    With `compare_calibration` the replay also gives the run's detector scores
    to every other calibration method, which takes longer; read the result
    with `GET /v1/dojo/runs/{run_id}/calibration`.
    """
    return await runs.create(
        run, created_by=member_id(caller), created_by_agent=agent_of(caller)
    )


@router.get("/runs/{run_id}", response_model=RunView, openapi_extra=OPEN_TO_AGENTS)
@read_limit
async def get_dojo_run(
    request: Request,
    run_id: str,
    runs: DojoRuns = Depends(get_dojo_runs),
):
    """One run with its design, bindings, progress and result counts.

    `stats` counts observations that produced no result, by reason, so a run
    with few results says whether alignment or rejection held them back.
    """
    return await runs.get(run_id)


@router.post(
    "/runs/{run_id}/cancel", response_model=RunView, openapi_extra=OPEN_TO_AGENTS
)
@write_limit
async def cancel_dojo_run(
    request: Request,
    run_id: str,
    caller: User | Agent = Depends(use_dojo),
    runs: DojoRuns = Depends(get_dojo_runs),
):
    """Cancel a run. A waiting run ends at once; a running one within seconds,
    keeping the results it stored so far. A key cancels only a run it queued."""
    return await runs.cancel(run_id, caller)


@router.post(
    "/runs/{run_id}/promote",
    response_model=RunPromotion,
    status_code=201,
    dependencies=[Depends(manage_monitors)],
)
@write_limit
async def promote_dojo_run(
    request: Request,
    run_id: str,
    promotion: RunPromote,
    runs: DojoRuns = Depends(get_dojo_runs),
):
    """Save the run's design as a new template in the pipeline library.

    Needs `manage_monitors` as well as `use_dojo`. `bindings` lists each
    input slot with the series it was bound to and, for a series copied from
    recorded history, its catalogue `reading_id`: the live input to suggest
    when the template starts a monitor. Uploaded series have none.
    """
    return await runs.promote(run_id, promotion)


@router.delete("/runs/{run_id}", status_code=204, openapi_extra=OPEN_TO_AGENTS)
@write_limit
async def delete_dojo_run(
    request: Request,
    run_id: str,
    caller: User | Agent = Depends(use_dojo),
    runs: DojoRuns = Depends(get_dojo_runs),
):
    """Delete a finished run and its results. This cannot be undone.

    A key deletes only a run it queued that no proposal that waits or was
    accepted and no monitor names as its test; others answer 403 or 409.
    """
    await runs.remove(run_id, caller)
    return Response(status_code=204)


@router.get(
    "/runs/{run_id}/metrics", response_model=RunMetrics, openapi_extra=OPEN_TO_AGENTS
)
@read_limit
async def get_dojo_run_metrics(
    request: Request,
    run_id: str,
    metrics: DojoMetrics = Depends(get_dojo_metrics),
):
    """Event metrics of a finished run against its dataset's current labels.

    Each label is one event: `detected` if the run alarmed inside it, with
    the delay from its start to the first alarm; `missed` if the run scored
    it without alarming; `unscored` if the run had no scores then, for
    example while the detector was still learning. `detection_rate` covers
    scored labels only. Alarm onsets outside every label are `false_alarms`,
    and `false_alarms_per_day` divides them by the scored time outside the
    labels. Only a run with status `succeeded` has metrics.
    """
    return await metrics.run(run_id)


@router.get(
    "/runs/{run_id}/calibration",
    response_model=MethodComparison,
    openapi_extra=OPEN_TO_AGENTS,
)
@read_limit
async def compare_dojo_run_calibration(
    request: Request,
    run_id: str,
    metrics: DojoMetrics = Depends(get_dojo_metrics),
):
    """Calibration methods side by side on the scores of one finished run.

    A run started with `compare_calibration` gave its detector scores to every
    other calibration method as well: the calibration window first, then each
    scored observation, as its own calibration step saw them. All methods aim
    at the alarm rate `alpha` and alarm after `consecutive` scores in a row
    above their boundary; the others run with their default settings.
    `methods` lists the run's own step first, then the fixed split and the
    methods that adapt. Each has the numbers of
    `GET /v1/dojo/runs/{run_id}/metrics` against the dataset's current labels,
    counted from the first result the methods judged, and `alarm_share`, the
    share of judged results it alarmed on. A method that stopped on these
    scores says why in `failed`. A run started without the comparison answers
    409.
    """
    return await metrics.calibration(run_id)


@router.get(
    "/runs/{run_id}/results",
    response_model=RunResultsPage,
    openapi_extra=OPEN_TO_AGENTS,
)
@read_limit
async def list_dojo_run_results(
    request: Request,
    run_id: str,
    query: Annotated[RunResultsQuery, Query()],
    runs: DojoRuns = Depends(get_dojo_runs),
):
    """One row per detector result, in order, a page at a time.

    Pass the returned `next_after` as `after` to continue; it is null on the
    last page. `score` is null while the detector is still learning.
    Pass `alarm=true` to read only the results that alarmed.
    """
    return await runs.results(run_id, query)


@router.get(
    "/runs/{run_id}/outline", response_model=RunOutline, openapi_extra=OPEN_TO_AGENTS
)
@read_limit
async def outline_dojo_run_results(
    request: Request,
    run_id: str,
    query: Annotated[RunOutlineQuery, Query()],
    runs: DojoRuns = Depends(get_dojo_runs),
):
    """A run's results summed up over equal stretches of time, for a chart.

    The time from the first to the last result is cut into `buckets` equal
    stretches. Each stretch that holds results says how many, how many of
    them alarmed, and the lowest and highest `score` and `threshold` among
    them, so a peak between two drawn points is not lost. Read `score` as
    in `GET /v1/dojo/runs/{run_id}/results`: `strategy` says whether it is
    a p-value or an anomaly score. A run still under way answers with the
    results it has stored so far.
    """
    return await runs.outline(run_id, query)


@router.get(
    "/runs/{run_id}/steps", response_model=RunSteps, openapi_extra=OPEN_TO_AGENTS
)
@read_limit
async def sample_dojo_run_steps(
    request: Request,
    run_id: str,
    runs: DojoRuns = Depends(get_dojo_runs),
):
    """What a few observations of a run looked like at every step.

    A run keeps 12 to 23 of its observations, spread from its first result
    to its last. Each says, by step of the design, which values went in and
    which came out (at most the first eight features of each), or why the
    step gave none: `state` is `ready`, `initializing`,
    `waiting_for_dependency`, `held_back`, `rejected` or `not_executed`,
    and `reason` says more. A detector's `output` is its score. The list
    is empty until the run has ended.
    """
    return await runs.steps(run_id)


@router.get("/suites", response_model=SuiteListPage, openapi_extra=OPEN_TO_AGENTS)
@read_limit
async def list_dojo_suites(
    request: Request,
    query: Annotated[SuiteListQuery, Query()],
    caller: User | Agent = Depends(use_dojo),
    suites: DojoSuites = Depends(get_dojo_suites),
):
    """Benchmark suites, newest first. `mine=true` keeps the caller's own."""
    return await suites.list_suites(query, caller)


@router.post(
    "/suites", response_model=SuiteView, status_code=201, openapi_extra=OPEN_TO_AGENTS
)
@write_limit
async def create_dojo_suite(
    request: Request,
    suite: SuiteCreate,
    caller: User | Agent = Depends(use_dojo),
    suites: DojoSuites = Depends(get_dojo_suites),
):
    """Fix up to 50 labelled datasets as a benchmark suite.

    A suite's datasets never change, so its studies stay comparable; to
    change the list, create a new suite with `derived_from`. A dataset in a
    suite cannot be deleted while the suite exists. A suite a key makes
    counts as `reviewed` only once a member reviews it.
    """
    return await suites.create_suite(
        suite, created_by=member_id(caller), created_by_agent=agent_of(caller)
    )


@router.post(
    "/suites/faults",
    response_model=SuiteView,
    status_code=201,
    openapi_extra=OPEN_TO_AGENTS,
)
@write_limit
async def create_dojo_fault_suite(
    request: Request,
    suite: FaultSuiteCreate,
    caller: User | Agent = Depends(use_dojo),
    suites: DojoSuites = Depends(get_dojo_suites),
):
    """Make a suite of labelled copies of one dataset with faults written in.

    Each copy gets `faults_per_copy` faults of the given `kinds` at places
    drawn from `seed`, after the `clean_share` of the span kept for warm-up,
    apart from each other and from the dataset's labels. A step or drift
    moves its series two to five standard deviations. The same request makes
    the same faults again.
    """
    return await suites.create_fault_suite(
        suite, created_by=member_id(caller), created_by_agent=agent_of(caller)
    )


@router.get(
    "/suites/{suite_id}", response_model=SuiteView, openapi_extra=OPEN_TO_AGENTS
)
@read_limit
async def get_dojo_suite(
    request: Request,
    suite_id: str,
    suites: DojoSuites = Depends(get_dojo_suites),
):
    """A suite with its datasets and its leaderboard.

    `leaderboard` ranks the complete studies, those with a finished, scored
    run on every dataset, by mean VUS-PR, then PR-AUC, then detection rate.
    `unfinished` lists the others. Metrics are calculated when a study is
    read with `GET /v1/dojo/studies/{study_id}`.
    """
    return await suites.get_suite(suite_id)


@router.patch("/suites/{suite_id}", response_model=SuiteView)
@write_limit
async def change_dojo_suite(
    request: Request,
    suite_id: str,
    change: SuiteChange,
    caller: User | Agent = Depends(use_dojo),
    suites: DojoSuites = Depends(get_dojo_suites),
):
    """Rename a suite or change its description; its datasets stay."""
    return await suites.change_suite(suite_id, change, caller)


@router.post("/suites/{suite_id}/review", response_model=SuiteView)
@write_limit
async def review_dojo_suite(
    request: Request,
    suite_id: str,
    caller: User | Agent = Depends(use_dojo),
    suites: DojoSuites = Depends(get_dojo_suites),
):
    """Vouch for a suite a key made, so its results count as reviewed."""
    if isinstance(caller, Agent):
        raise HTTPException(status_code=403, detail="Only a member reviews a suite")
    return await suites.review_suite(suite_id, reviewed_by=caller.id)


@router.delete("/suites/{suite_id}", status_code=204, openapi_extra=OPEN_TO_AGENTS)
@write_limit
async def delete_dojo_suite(
    request: Request,
    suite_id: str,
    caller: User | Agent = Depends(use_dojo),
    suites: DojoSuites = Depends(get_dojo_suites),
):
    """Delete a suite with its studies and their runs. This cannot be undone.

    A run a proposal or a monitor names as its test stays on its dataset.
    A key deletes only a suite it made, holding only its own studies.
    """
    await suites.remove_suite(suite_id, caller)
    return Response(status_code=204)


@router.get(
    "/suites/{suite_id}/comparison",
    response_model=StudyComparison,
    openapi_extra=OPEN_TO_AGENTS,
)
@read_limit
async def compare_dojo_studies(
    request: Request,
    suite_id: str,
    query: Annotated[StudyComparisonQuery, Query()],
    suites: DojoSuites = Depends(get_dojo_suites),
):
    """Two studies of a suite, dataset by dataset.

    For `metric` (default `vus_pr`) each dataset gets the baseline's value,
    the challenger's and their difference; `wins`, `losses` and `ties` count
    the datasets, and `p_value` is the two-sided Wilcoxon signed-rank test of
    the differences.
    """
    return await suites.compare_studies(suite_id, query)


@router.get("/studies", response_model=StudyListPage, openapi_extra=OPEN_TO_AGENTS)
@read_limit
async def list_dojo_studies(
    request: Request,
    query: Annotated[StudyListQuery, Query()],
    caller: User | Agent = Depends(use_dojo),
    suites: DojoSuites = Depends(get_dojo_suites),
):
    """Studies, newest first, optionally of one suite."""
    return await suites.list_studies(query, caller)


@router.post(
    "/studies", response_model=StudyView, status_code=201, openapi_extra=OPEN_TO_AGENTS
)
@write_limit
async def create_dojo_study(
    request: Request,
    study: StudyCreate,
    caller: User | Agent = Depends(use_dojo),
    suites: DojoSuites = Depends(get_dojo_suites),
):
    """Queue one design over every dataset of a suite, one run each.

    `bindings` maps input slot ids to a series name looked up in every
    dataset; a slot left out takes the series named like the slot, or a
    dataset's only series when the design has one input. Every dataset must
    bind, or nothing is queued. The study's runs take one place among the 20
    that may wait or run at once, and the worker runs single runs first.
    """
    return await suites.create_study(
        study, created_by=member_id(caller), created_by_agent=agent_of(caller)
    )


@router.get(
    "/studies/{study_id}", response_model=StudyView, openapi_extra=OPEN_TO_AGENTS
)
@read_limit
async def get_dojo_study(
    request: Request,
    study_id: str,
    suites: DojoSuites = Depends(get_dojo_suites),
):
    """A study with each dataset's run and metrics.

    Reading it calculates the metrics of finished runs for a few seconds;
    `metrics_pending` counts those still to come, so read it again until it
    is 0.
    """
    return await suites.get_study(study_id, calculate=True)


@router.post(
    "/studies/{study_id}/cancel",
    response_model=StudyView,
    openapi_extra=OPEN_TO_AGENTS,
)
@write_limit
async def cancel_dojo_study(
    request: Request,
    study_id: str,
    caller: User | Agent = Depends(use_dojo),
    suites: DojoSuites = Depends(get_dojo_suites),
):
    """Cancel the study's waiting and running runs."""
    return await suites.cancel_study(study_id, caller)


@router.delete("/studies/{study_id}", status_code=204, openapi_extra=OPEN_TO_AGENTS)
@write_limit
async def delete_dojo_study(
    request: Request,
    study_id: str,
    caller: User | Agent = Depends(use_dojo),
    suites: DojoSuites = Depends(get_dojo_suites),
):
    """Delete a study and its runs. A key deletes only a study it queued."""
    await suites.remove_study(study_id, caller)
    return Response(status_code=204)
