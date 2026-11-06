"""Dojo datasets and runs: replay detection designs over stored time series.

Open to members whose role grants the Dojo permission.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from off_key_core.auth.permissions import Permission
from off_key_core.db.models import User
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
    LabelChange,
    LabelCreate,
    LabelList,
    LabelView,
    RunCreate,
    RunListPage,
    RunListQuery,
    RunMetrics,
    RunPromote,
    RunPromotion,
    RunResultsPage,
    RunResultsQuery,
    RunView,
)

from ...provider import (
    get_dojo_datasets,
    get_dojo_labels,
    get_dojo_metrics,
    get_dojo_runs,
)
from ...services.dojo.datasets import DojoDatasets
from ...services.dojo.labels import DojoLabels
from ...services.dojo.metrics import DojoMetrics
from ...services.dojo.runs import DojoRuns
from ..collection_auth import require_permission
from ..errors import DomainErrorRoute

use_dojo = require_permission(Permission.use_dojo)
manage_monitors = require_permission(Permission.manage_monitors)

router = APIRouter(
    prefix="/dojo",
    tags=["dojo"],
    dependencies=[Depends(use_dojo)],
    route_class=DomainErrorRoute,
)


@router.get("/datasets", response_model=DatasetListPage)
async def list_datasets(
    query: Annotated[DatasetListQuery, Query()],
    datasets: DojoDatasets = Depends(get_dojo_datasets),
):
    return await datasets.list(query)


@router.post("/datasets/csv", response_model=DatasetView, status_code=201)
async def import_csv_dataset(
    request: Request,
    query: Annotated[CsvImportQuery, Query()],
    user: User = Depends(use_dojo),
    datasets: DojoDatasets = Depends(get_dojo_datasets),
):
    body = await request.body()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Upload at most 100 MB of CSV")
    return await datasets.import_csv(body, query, created_by=user.id)


@router.post("/datasets/history", response_model=DatasetView, status_code=201)
async def import_history_dataset(
    change: DatasetFromHistory,
    user: User = Depends(use_dojo),
    datasets: DojoDatasets = Depends(get_dojo_datasets),
):
    return await datasets.import_history(change, created_by=user.id)


@router.get("/datasets/{dataset_id}", response_model=DatasetView)
async def get_dataset(
    dataset_id: str, datasets: DojoDatasets = Depends(get_dojo_datasets)
):
    return await datasets.get(dataset_id)


@router.patch("/datasets/{dataset_id}", response_model=DatasetView)
async def change_dataset(
    dataset_id: str,
    change: DatasetChange,
    datasets: DojoDatasets = Depends(get_dojo_datasets),
):
    return await datasets.change(dataset_id, change)


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(
    dataset_id: str, datasets: DojoDatasets = Depends(get_dojo_datasets)
):
    await datasets.remove(dataset_id)


@router.get(
    "/datasets/{dataset_id}/series/{series_id}/points",
    response_model=DatasetPointsPage,
)
async def list_dataset_points(
    dataset_id: str,
    series_id: str,
    query: Annotated[DatasetPointsQuery, Query()],
    datasets: DojoDatasets = Depends(get_dojo_datasets),
):
    return await datasets.points(dataset_id, series_id, query)


@router.get("/datasets/{dataset_id}/labels", response_model=LabelList)
async def list_dataset_labels(
    dataset_id: str, labels: DojoLabels = Depends(get_dojo_labels)
):
    return await labels.list(dataset_id)


@router.post("/datasets/{dataset_id}/labels", response_model=LabelView, status_code=201)
async def create_dataset_label(
    dataset_id: str,
    request: LabelCreate,
    user: User = Depends(use_dojo),
    labels: DojoLabels = Depends(get_dojo_labels),
):
    return await labels.create(dataset_id, request, created_by=user.id)


@router.patch("/datasets/{dataset_id}/labels/{label_id}", response_model=LabelView)
async def change_dataset_label(
    dataset_id: str,
    label_id: str,
    change: LabelChange,
    labels: DojoLabels = Depends(get_dojo_labels),
):
    return await labels.change(dataset_id, label_id, change)


@router.delete("/datasets/{dataset_id}/labels/{label_id}", status_code=204)
async def delete_dataset_label(
    dataset_id: str, label_id: str, labels: DojoLabels = Depends(get_dojo_labels)
):
    await labels.remove(dataset_id, label_id)


@router.get("/datasets/{dataset_id}/comparison", response_model=Comparison)
async def compare_dataset_runs(
    dataset_id: str,
    query: Annotated[ComparisonQuery, Query()],
    metrics: DojoMetrics = Depends(get_dojo_metrics),
):
    return await metrics.compare(dataset_id, query)


@router.get("/runs", response_model=RunListPage)
async def list_runs(
    query: Annotated[RunListQuery, Query()],
    runs: DojoRuns = Depends(get_dojo_runs),
):
    return await runs.list(query)


@router.post("/runs", response_model=RunView, status_code=201)
async def create_run(
    request: RunCreate,
    user: User = Depends(use_dojo),
    runs: DojoRuns = Depends(get_dojo_runs),
):
    return await runs.create(request, created_by=user.id)


@router.get("/runs/{run_id}", response_model=RunView)
async def get_run(run_id: str, runs: DojoRuns = Depends(get_dojo_runs)):
    return await runs.get(run_id)


@router.post("/runs/{run_id}/cancel", response_model=RunView)
async def cancel_run(run_id: str, runs: DojoRuns = Depends(get_dojo_runs)):
    return await runs.cancel(run_id)


@router.post(
    "/runs/{run_id}/promote",
    response_model=RunPromotion,
    status_code=201,
    dependencies=[Depends(manage_monitors)],
)
async def promote_run(
    run_id: str, request: RunPromote, runs: DojoRuns = Depends(get_dojo_runs)
):
    return await runs.promote(run_id, request)


@router.delete("/runs/{run_id}", status_code=204)
async def delete_run(run_id: str, runs: DojoRuns = Depends(get_dojo_runs)):
    await runs.remove(run_id)


@router.get("/runs/{run_id}/metrics", response_model=RunMetrics)
async def get_run_metrics(
    run_id: str, metrics: DojoMetrics = Depends(get_dojo_metrics)
):
    return await metrics.run(run_id)


@router.get("/runs/{run_id}/results", response_model=RunResultsPage)
async def list_run_results(
    run_id: str,
    query: Annotated[RunResultsQuery, Query()],
    runs: DojoRuns = Depends(get_dojo_runs),
):
    return await runs.results(run_id, query)
