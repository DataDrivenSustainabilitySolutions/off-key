"""Dojo datasets: CSV uploads and copies of recorded readings.

Every call is forwarded to TACTIC with the caller's own token, which decides
access. Administrators only until members get a dedicated Dojo permission.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
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
from off_key_core.schemas.members import MemberProfile

from ...facades.tactic import path_segment, tactic
from ..access import member_authorization, require_admin
from ..errors import TacticErrorRoute
from ..rate_limiter import limiter


async def member_scope(
    request: Request, member: MemberProfile = Depends(require_admin)
):
    request.state.dojo_member_id = str(member.id)


def member_key(request: Request) -> str:
    return request.state.dojo_member_id


router = APIRouter(dependencies=[Depends(member_scope)], route_class=TacticErrorRoute)
read_limit = limiter.shared_limit("240/minute", scope="dojo-reads", key_func=member_key)
write_limit = limiter.shared_limit(
    "30/minute", scope="dojo-writes", key_func=member_key
)
upload_limit = limiter.shared_limit(
    "6/minute", scope="dojo-uploads", key_func=member_key
)


def _query(model) -> dict:
    return model.model_dump(mode="json", exclude_none=True)


@router.get("/datasets", response_model=DatasetListPage)
@read_limit
async def list_dojo_datasets(
    request: Request,
    query: Annotated[DatasetListQuery, Query()],
    authorization: str = Depends(member_authorization),
):
    """Datasets in the Dojo, newest first, with their size and time span."""
    return await tactic.request(
        "GET",
        "/api/v1/dojo/datasets",
        params=_query(query),
        headers={"Authorization": authorization},
    )


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
    authorization: str = Depends(member_authorization),
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
    return await tactic.request(
        "POST",
        "/api/v1/dojo/datasets/csv",
        params=_query(query),
        headers={"Authorization": authorization},
        content=body,
        content_type="text/csv",
    )


@router.post("/datasets/history", response_model=DatasetView, status_code=201)
@write_limit
async def import_dojo_history(
    request: Request,
    change: DatasetFromHistory,
    authorization: str = Depends(member_authorization),
):
    """Create a dataset by copying recorded readings for one time window.

    `reading_ids` are catalogue stream ids from `GET /v1/system`. Each becomes
    one series named after the reading. The copy is frozen: later retention
    or catalogue edits do not change it.
    """
    return await tactic.request(
        "POST",
        "/api/v1/dojo/datasets/history",
        json_data=change.model_dump(mode="json"),
        headers={"Authorization": authorization},
    )


@router.get("/datasets/{dataset_id}", response_model=DatasetView)
@read_limit
async def get_dojo_dataset(
    request: Request,
    dataset_id: str,
    authorization: str = Depends(member_authorization),
):
    """One dataset with its series, their units and time spans."""
    return await tactic.request(
        "GET",
        f"/api/v1/dojo/datasets/{path_segment(dataset_id)}",
        headers={"Authorization": authorization},
    )


@router.patch("/datasets/{dataset_id}", response_model=DatasetView)
@write_limit
async def change_dojo_dataset(
    request: Request,
    dataset_id: str,
    change: DatasetChange,
    authorization: str = Depends(member_authorization),
):
    """Rename a dataset or change its description."""
    return await tactic.request(
        "PATCH",
        f"/api/v1/dojo/datasets/{path_segment(dataset_id)}",
        json_data=change.model_dump(mode="json", exclude_none=True),
        headers={"Authorization": authorization},
    )


@router.delete("/datasets/{dataset_id}", status_code=204)
@write_limit
async def delete_dojo_dataset(
    request: Request,
    dataset_id: str,
    authorization: str = Depends(member_authorization),
):
    """Delete a dataset and all its values. This cannot be undone."""
    await tactic.request(
        "DELETE",
        f"/api/v1/dojo/datasets/{path_segment(dataset_id)}",
        headers={"Authorization": authorization},
    )
    return Response(status_code=204)


@router.get(
    "/datasets/{dataset_id}/series/{series_id}/points",
    response_model=DatasetPointsPage,
)
@read_limit
async def list_dojo_points(
    request: Request,
    dataset_id: str,
    series_id: str,
    query: Annotated[DatasetPointsQuery, Query()],
    authorization: str = Depends(member_authorization),
):
    """The values of one series in time order, a page at a time.

    Pass the returned `next_after` as `after` to continue; it is null on the
    last page.
    """
    return await tactic.request(
        "GET",
        f"/api/v1/dojo/datasets/{path_segment(dataset_id)}"
        f"/series/{path_segment(series_id)}/points",
        params=_query(query),
        headers={"Authorization": authorization},
    )
