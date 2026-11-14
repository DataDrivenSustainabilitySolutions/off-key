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
    Comparison,
    ComparisonQuery,
    CsvImportQuery,
    DatasetChange,
    DatasetFromHistory,
    DatasetListPage,
    DatasetListQuery,
    DatasetPointsPage,
    DatasetPointsQuery,
    DatasetView,
    LabelBatch,
    LabelChange,
    LabelCreate,
    LabelList,
    LabelSuggestionList,
    LabelSuggestionQuery,
    LabelView,
    MethodComparison,
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
)
from off_key_tactic_middleware.services.dojo.datasets import DojoDatasets
from off_key_tactic_middleware.services.dojo.labels import DojoLabels
from off_key_tactic_middleware.services.dojo.metrics import DojoMetrics
from off_key_tactic_middleware.services.dojo.runs import DojoRuns

from ...providers import (
    get_dojo_datasets,
    get_dojo_labels,
    get_dojo_metrics,
    get_dojo_runs,
)
from ..access import caller_key, member_id, require_permission
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
    datasets: DojoDatasets = Depends(get_dojo_datasets),
):
    """Datasets in the Dojo, newest first, with their size and time span."""
    return await datasets.list(query)


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
    return await datasets.import_history(change, created_by=member_id(caller))


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


@router.delete("/datasets/{dataset_id}", status_code=204)
@write_limit
async def delete_dojo_dataset(
    request: Request,
    dataset_id: str,
    datasets: DojoDatasets = Depends(get_dojo_datasets),
):
    """Delete a dataset and all its values. This cannot be undone."""
    await datasets.remove(dataset_id)
    return Response(status_code=204)


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
    runs: DojoRuns = Depends(get_dojo_runs),
):
    """Runs, newest first, optionally of one dataset or in one status."""
    return await runs.list(query)


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
    return await runs.create(run, created_by=member_id(caller))


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


@router.post("/runs/{run_id}/cancel", response_model=RunView)
@write_limit
async def cancel_dojo_run(
    request: Request,
    run_id: str,
    runs: DojoRuns = Depends(get_dojo_runs),
):
    """Cancel a run. A waiting run ends at once; a running one within seconds,
    keeping the results it stored so far."""
    return await runs.cancel(run_id)


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


@router.delete("/runs/{run_id}", status_code=204)
@write_limit
async def delete_dojo_run(
    request: Request,
    run_id: str,
    runs: DojoRuns = Depends(get_dojo_runs),
):
    """Delete a finished run and its results. This cannot be undone."""
    await runs.remove(run_id)
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
