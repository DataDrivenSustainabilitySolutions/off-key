"""Dojo datasets: upload or copy time series for offline comparison runs.

Administrators only until members get a dedicated Dojo permission.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from off_key_core.db.models import User
from off_key_core.schemas.dojo import (
    MAX_UPLOAD_BYTES,
    CsvImportQuery,
    DatasetChange,
    DatasetFromHistory,
    DatasetListPage,
    DatasetListQuery,
    DatasetPointsPage,
    DatasetPointsQuery,
    DatasetView,
)

from ...provider import get_dojo_datasets
from ...services.dojo.datasets import DojoDatasets
from ..collection_auth import require_admin
from ..errors import DomainErrorRoute

router = APIRouter(
    prefix="/dojo",
    tags=["dojo"],
    dependencies=[Depends(require_admin)],
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
    user: User = Depends(require_admin),
    datasets: DojoDatasets = Depends(get_dojo_datasets),
):
    body = await request.body()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Upload at most 100 MB of CSV")
    return await datasets.import_csv(body, query, created_by=user.id)


@router.post("/datasets/history", response_model=DatasetView, status_code=201)
async def import_history_dataset(
    change: DatasetFromHistory,
    user: User = Depends(require_admin),
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
