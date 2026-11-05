"""Forward saved system requests with member authorization preserved."""

from fastapi import APIRouter, Depends, Path, Query, Response
from off_key_core.schemas.collection_rules import SystemCollectionRuleChange
from off_key_core.schemas.storage import StorageStatus
from off_key_core.schemas.system import (
    SystemChange,
    SystemConnectionCheck,
    SystemConnectionCheckScope,
)
from off_key_core.schemas.system_collection import (
    SystemCollectionChange,
    SystemCollectionScope,
)
from off_key_core.schemas.system_live import SystemLiveScope, SystemLiveStart

from ...facades.tactic import tactic
from ..access import member_authorization
from ..errors import TacticErrorRoute

router = APIRouter(route_class=TacticErrorRoute)


async def system_request(
    method: str,
    authorization: str,
    path: str = "",
    body: dict | None = None,
):
    return await tactic.request(
        method,
        f"/api/v1/system{path}",
        json_data=body,
        headers={"Authorization": authorization},
    )


@router.get("")
async def get_system(authorization: str = Depends(member_authorization)):
    """The saved catalogue and how it runs now.

    `document` holds brokers (`connections`), `devices`, readings (`streams`) and
    `groups`; `revision` is the value to send as `expected_revision` when saving;
    `runtime.bindings` maps each recorded stream id to its `entity_id`
    (`charger_id`) and `telemetry_key` (`telemetry_type`); `can_edit` says
    whether the caller may change it.
    """
    return await system_request("GET", authorization)


@router.get("/health")
async def get_collection_health(authorization: str = Depends(member_authorization)):
    """Raw state of the collector and broker workers, for System status."""
    return await system_request("GET", authorization, "/health")


@router.get("/storage", response_model=StorageStatus)
async def get_storage_status(authorization: str = Depends(member_authorization)):
    """Database size, retention policies and the storage cap."""
    return await system_request("GET", authorization, "/storage")


@router.put("")
async def save_system(
    change: SystemChange, authorization: str = Depends(member_authorization)
):
    """Replace the saved catalogue. Administrators only.

    Send the whole `document` with the `revision` you read as
    `expected_revision`; a stale revision answers 409. A change to readings
    that running monitors use answers 409 unless `pause_affected_monitors` is
    set, which pauses those monitors first.
    """
    return await system_request(
        "PUT", authorization, body=change.model_dump(mode="json")
    )


@router.post("/connections/check", response_model=SystemConnectionCheck)
async def check_broker_connection(
    scope: SystemConnectionCheckScope,
    authorization: str = Depends(member_authorization),
):
    """Connect once to a saved broker and disconnect; nothing is subscribed.

    Administrators only.
    """
    return await system_request(
        "POST", authorization, "/connections/check", scope.model_dump(mode="json")
    )


@router.post("/connections/reconnect")
async def reconnect_broker(
    scope: SystemConnectionCheckScope,
    authorization: str = Depends(member_authorization),
):
    """Retry a recorded broker now instead of waiting for its backoff.

    Administrators only.
    """
    return await system_request(
        "POST", authorization, "/connections/reconnect", scope.model_dump(mode="json")
    )


@router.get("/revisions")
async def list_system_revisions(authorization: str = Depends(member_authorization)):
    """The last 50 saved catalogue revisions, newest first, with who saved them."""
    return await system_request("GET", authorization, "/revisions")


@router.post("/collection/preview")
async def preview_collection(
    change: SystemCollectionChange | SystemCollectionRuleChange,
    authorization: str = Depends(member_authorization),
):
    """Preview a recording change without applying it. Administrators only.

    Answers how many readings would start, stop or change rate, the expected
    rows per day and the running monitors the change would affect.
    """
    return await system_request(
        "POST", authorization, "/collection/preview", change.model_dump(mode="json")
    )


@router.post("/collection/status")
async def get_collection_status(
    scope: SystemCollectionScope, authorization: str = Depends(member_authorization)
):
    """Recording state of the given readings (catalogue stream ids)."""
    return await system_request(
        "POST", authorization, "/collection/status", scope.model_dump(mode="json")
    )


@router.put("/collection")
async def apply_collection(
    change: SystemCollectionChange | SystemCollectionRuleChange,
    authorization: str = Depends(member_authorization),
):
    """Change which readings are recorded. Administrators only.

    Takes the same body as the preview; affected monitors answer 409 unless
    `pause_affected_monitors` is set. Answers with the saved catalogue.
    """
    return await system_request(
        "PUT", authorization, "/collection", change.model_dump(mode="json")
    )


@router.get("/live")
async def get_live_readings(
    after_sequence: int = Query(default=0, ge=0),
    authorization: str = Depends(member_authorization),
):
    """Latest values from open live previews, after the given sequence number.

    Administrators only.
    """
    return await system_request(
        "GET", authorization, f"/live?after_sequence={after_sequence}"
    )


@router.post("/live/leases")
async def start_live_view(
    change: SystemLiveStart, authorization: str = Depends(member_authorization)
):
    """Start a live preview of configured readings without recording them.

    The preview is a lease: renew it while it is needed, otherwise it ends on
    its own. Nothing is stored. Administrators only.
    """
    return await system_request(
        "POST",
        authorization,
        "/live/leases",
        change.model_dump(mode="json", exclude_none=True),
    )


@router.put("/live/leases/{lease_id}")
async def renew_live_view(
    lease_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    authorization: str = Depends(member_authorization),
    change: SystemLiveScope | None = None,
):
    """Keep a live preview open, optionally with other readings. Administrators only."""
    return await system_request(
        "PUT",
        authorization,
        f"/live/leases/{lease_id}",
        change.model_dump(mode="json") if change else None,
    )


@router.delete("/live/leases/{lease_id}", status_code=204)
async def stop_live_view(
    lease_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    authorization: str = Depends(member_authorization),
):
    """End a live preview. Administrators only."""
    await system_request("DELETE", authorization, f"/live/leases/{lease_id}")
    return Response(status_code=204)
