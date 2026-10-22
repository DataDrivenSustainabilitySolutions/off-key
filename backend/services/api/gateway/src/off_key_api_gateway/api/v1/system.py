"""Forward saved system requests with member authorization preserved."""

from fastapi import APIRouter, Header, HTTPException, Path, Query, Response
from off_key_core.schemas.collection_rules import SystemCollectionRuleChange
from off_key_core.schemas.storage import StorageStatus
from off_key_core.schemas.system import SystemChange
from off_key_core.schemas.system_collection import (
    SystemCollectionChange,
    SystemCollectionScope,
)
from off_key_core.schemas.system_live import SystemLiveScope, SystemLiveStart

from ...facades.tactic import tactic
from ..errors import TacticErrorRoute

router = APIRouter(route_class=TacticErrorRoute)


async def system_request(
    method: str,
    authorization: str | None,
    path: str = "",
    body: dict | None = None,
):
    if not authorization:
        raise HTTPException(401, "Sign in to view the saved system")
    return await tactic._make_request(
        method,
        f"/api/v1/system{path}",
        json_data=body,
        headers={"Authorization": authorization},
    )


@router.get("")
async def get_system(authorization: str | None = Header(default=None)):
    return await system_request("GET", authorization)


@router.get("/health")
async def collection_health(authorization: str | None = Header(default=None)):
    return await system_request("GET", authorization, "/health")


@router.get("/storage", response_model=StorageStatus)
async def storage_status(authorization: str | None = Header(default=None)):
    return await system_request("GET", authorization, "/storage")


@router.put("")
async def save_system(
    change: SystemChange, authorization: str | None = Header(default=None)
):
    return await system_request(
        "PUT", authorization, body=change.model_dump(mode="json")
    )


@router.get("/revisions")
async def list_revisions(authorization: str | None = Header(default=None)):
    return await system_request("GET", authorization, "/revisions")


@router.post("/collection/preview")
async def preview_collection(
    change: SystemCollectionChange | SystemCollectionRuleChange,
    authorization: str | None = Header(default=None),
):
    return await system_request(
        "POST", authorization, "/collection/preview", change.model_dump(mode="json")
    )


@router.post("/collection/status")
async def collection_status(
    scope: SystemCollectionScope, authorization: str | None = Header(default=None)
):
    return await system_request(
        "POST", authorization, "/collection/status", scope.model_dump(mode="json")
    )


@router.put("/collection")
async def apply_collection(
    change: SystemCollectionChange | SystemCollectionRuleChange,
    authorization: str | None = Header(default=None),
):
    return await system_request(
        "PUT", authorization, "/collection", change.model_dump(mode="json")
    )


@router.get("/live")
async def get_live(
    after_sequence: int = Query(default=0, ge=0),
    authorization: str | None = Header(default=None),
):
    return await system_request(
        "GET", authorization, f"/live?after_sequence={after_sequence}"
    )


@router.post("/live/leases")
async def start_live(
    change: SystemLiveStart, authorization: str | None = Header(default=None)
):
    return await system_request(
        "POST",
        authorization,
        "/live/leases",
        change.model_dump(mode="json", exclude_none=True),
    )


@router.put("/live/leases/{lease_id}")
async def renew_live(
    lease_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    authorization: str | None = Header(default=None),
    change: SystemLiveScope | None = None,
):
    return await system_request(
        "PUT",
        authorization,
        f"/live/leases/{lease_id}",
        change.model_dump(mode="json") if change else None,
    )


@router.delete("/live/leases/{lease_id}", status_code=204)
async def stop_live(
    lease_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    authorization: str | None = Header(default=None),
):
    await system_request("DELETE", authorization, f"/live/leases/{lease_id}")
    return Response(status_code=204)
