"""The catalogue, its recording, brokers, storage and live views.

TACTIC enforces `manage_sources` on changes; the gateway forwards the member's
credential and answers with the public field names.
"""

from typing import Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from off_key_core.schemas.collection_health import CollectionHealth
from off_key_core.schemas.collection_rules import (
    CollectionRule,
    CollectionRuleScope,
    SystemCollectionRuleChange,
)
from off_key_core.schemas.public_names import public
from off_key_core.schemas.storage import StorageStatus
from off_key_core.schemas.system import (
    SystemChange,
    SystemConnectionCheck,
    SystemConnectionCheckScope,
    SystemDocument,
)
from off_key_core.schemas.system_collection import (
    SystemCollectionChange,
    SystemCollectionScope,
)
from off_key_core.schemas.system_live import SystemLiveScope, SystemLiveStart
from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema

from ...facades.tactic import tactic
from ..access import member_authorization
from ..errors import TacticErrorRoute

router = APIRouter(route_class=TacticErrorRoute)
brokers_router = APIRouter(route_class=TacticErrorRoute)
recording_router = APIRouter(route_class=TacticErrorRoute)
storage_router = APIRouter(route_class=TacticErrorRoute)
live_router = APIRouter(route_class=TacticErrorRoute)

VIEW_ID = Path(pattern=r"^[0-9a-f]{32}$")


class _Open(BaseModel):
    """A TACTIC answer whose other fields pass through unchanged."""

    model_config = ConfigDict(extra="allow")


class PolicyOrigin(_Open):
    """The recording rule a reading follows, if any."""

    scope: CollectionRuleScope | None = None


class RecordedReading(_Open):
    """How one reading is recorded: broker, policy and the rule behind it."""

    connection_id: str | None = Field(
        default=None, **public("broker_id", "connection_id")
    )
    policy_origin: PolicyOrigin | None = None
    # How TACTIC stores the reading; the API names readings by id only.
    entity_id: SkipJsonSchema[str | None] = Field(default=None, exclude=True)
    telemetry_key: SkipJsonSchema[str | None] = Field(default=None, exclude=True)
    accepted_topic: SkipJsonSchema[str | None] = Field(default=None, exclude=True)


class CatalogueRuntime(_Open):
    """What runs now. `bindings` is keyed by reading id; `ingress` and
    `collection` are the raw reports of the recording workers."""

    bindings: dict[str, RecordedReading] = Field(default_factory=dict)
    collection_rules: list[CollectionRule] = Field(default_factory=list)


class Catalogue(_Open):
    revision: int
    document: SystemDocument
    runtime: CatalogueRuntime
    can_edit: bool


class RecordingStatus(_Open):
    revision: int
    runtime: CatalogueRuntime


class RecordingPreview(_Open):
    bindings: dict[str, RecordedReading] = Field(default_factory=dict)
    rules: list[CollectionRule] = Field(default_factory=list)


class BrokerReconnect(BaseModel):
    connection_id: str = Field(**public("broker_id", "connection_id"))


class LiveBroker(_Open):
    connection_id: str = Field(**public("broker_id", "connection_id"))


class LiveReading(_Open):
    stream_id: str = Field(**public("reading_id", "stream_id"))


class LiveMeasurements(_Open):
    connections: list[LiveBroker] = Field(
        default_factory=list, **public("brokers", "connections")
    )
    streams: list[LiveReading] = Field(
        default_factory=list, **public("readings", "streams")
    )
    samples: list[LiveReading] = Field(default_factory=list)


class LiveView(_Open):
    lease_id: str = Field(**public("view_id", "lease_id"))
    expires_in_seconds: int
    telemetry: LiveMeasurements = Field(**public("measurements", "telemetry"))


async def system_request(
    method: str,
    authorization: str,
    path: str = "",
    body: Any = None,
):
    return await tactic.request(
        method,
        f"/api/v1/system{path}",
        json_data=body,
        headers={"Authorization": authorization},
    )


def _dump(model: BaseModel, **options) -> dict:
    """TACTIC reads the internal field names."""
    return model.model_dump(mode="json", **options)


@router.get("", response_model=Catalogue)
async def get_catalogue(
    request: Request, authorization: str = Depends(member_authorization)
):
    """The saved catalogue and how it is recorded now.

    `document` holds `brokers`, `devices`, `readings` and `groups`; `revision`
    is the value to send as `expected_revision` when saving;
    `runtime.bindings` says per reading id how it is recorded;
    `can_edit` says whether the caller may change it.
    """
    result = await system_request("GET", authorization)
    if getattr(request.state, "demo_guest", False):
        result = {**result, "updated_by": None, "can_edit": False}
    return result


@router.put("", response_model=Catalogue)
async def save_catalogue(
    change: SystemChange, authorization: str = Depends(member_authorization)
):
    """Replace the saved catalogue. Needs `manage_sources`.

    Send the whole `document` with the `revision` you read as
    `expected_revision`; a stale revision answers 409. A change to readings
    that running monitors use answers 409 unless `pause_affected_monitors` is
    set, which pauses those monitors first.
    """
    return await system_request("PUT", authorization, body=_dump(change))


@router.get("/revisions")
async def list_catalogue_revisions(
    authorization: str = Depends(member_authorization),
):
    """The last 50 saved catalogue revisions, newest first, with who saved them."""
    return await system_request("GET", authorization, "/revisions")


@brokers_router.post("/check", response_model=SystemConnectionCheck)
async def check_broker(
    scope: SystemConnectionCheckScope,
    authorization: str = Depends(member_authorization),
):
    """Connect once to a saved broker and disconnect; nothing is subscribed.

    Needs `manage_sources`.
    """
    return await system_request(
        "POST", authorization, "/connections/check", _dump(scope)
    )


@brokers_router.post("/{broker_id}/reconnect", response_model=BrokerReconnect)
async def reconnect_broker(
    broker_id: str = Path(min_length=1, max_length=280),
    authorization: str = Depends(member_authorization),
):
    """Retry a recorded broker now instead of waiting for its backoff.

    Needs `manage_sources`.
    """
    scope = SystemConnectionCheckScope(connection_id=broker_id)
    return await system_request(
        "POST", authorization, "/connections/reconnect", _dump(scope)
    )


@recording_router.put("", response_model=Catalogue)
async def change_recording(
    change: SystemCollectionChange | SystemCollectionRuleChange,
    authorization: str = Depends(member_authorization),
):
    """Change which readings are recorded and how. Needs `manage_sources`.

    Either set one `policy` for `reading_ids`, or send `rule_changes` for a
    broker, topic or reading scope. Affected monitors answer 409 unless
    `pause_affected_monitors` is set. Answers with the saved catalogue.
    """
    return await system_request("PUT", authorization, "/collection", _dump(change))


@recording_router.post("/preview", response_model=RecordingPreview)
async def preview_recording(
    change: SystemCollectionChange | SystemCollectionRuleChange,
    authorization: str = Depends(member_authorization),
):
    """Preview a recording change without applying it. Needs `manage_sources`.

    Answers how many readings would start, stop or change rate, the expected
    rows per day and the running monitors the change would affect.
    """
    return await system_request(
        "POST", authorization, "/collection/preview", _dump(change)
    )


@recording_router.post("/status", response_model=RecordingStatus)
async def get_recording_status(
    scope: SystemCollectionScope, authorization: str = Depends(member_authorization)
):
    """Recording state of the given `reading_ids` and their brokers."""
    return await system_request(
        "POST", authorization, "/collection/status", _dump(scope)
    )


@recording_router.get("/health", response_model=CollectionHealth)
async def get_recording_health(authorization: str = Depends(member_authorization)):
    """Whether readings are being recorded, and what to fix if not.

    `diagnosis` names the first failing check (`code`, `tone`, `title`,
    `explanation`) so a caller needs no rules of its own. The raw collector and
    broker reports it was decided from are included for detail views.
    """
    return await system_request("GET", authorization, "/health")


@storage_router.get("", response_model=StorageStatus)
async def get_storage(authorization: str = Depends(member_authorization)):
    """Database size, retention policies and the storage cap."""
    return await system_request("GET", authorization, "/storage")


@live_router.get("/measurements", response_model=LiveMeasurements)
async def list_live_measurements(
    after_sequence: int = Query(default=0, ge=0),
    authorization: str = Depends(member_authorization),
):
    """Latest values from open live views, after the given sequence number.

    Needs `manage_sources`.
    """
    return await system_request(
        "GET", authorization, f"/live?after_sequence={after_sequence}"
    )


@live_router.post("/views", response_model=LiveView)
async def open_live_view(
    change: SystemLiveStart, authorization: str = Depends(member_authorization)
):
    """Watch configured readings live without recording them.

    The view ends on its own unless it is renewed while needed. Nothing is
    stored. Needs `manage_sources`.
    """
    return await system_request(
        "POST", authorization, "/live/leases", _dump(change, exclude_none=True)
    )


@live_router.post("/views/{view_id}/renew", response_model=LiveView)
async def renew_live_view(
    view_id: str = VIEW_ID,
    authorization: str = Depends(member_authorization),
    change: SystemLiveScope | None = None,
):
    """Keep a live view open, optionally with other `reading_ids`.

    Needs `manage_sources`.
    """
    return await system_request(
        "PUT",
        authorization,
        f"/live/leases/{view_id}",
        _dump(change) if change else None,
    )


@live_router.delete("/views/{view_id}", status_code=204)
async def close_live_view(
    view_id: str = VIEW_ID,
    authorization: str = Depends(member_authorization),
):
    """End a live view. Needs `manage_sources`."""
    await system_request("DELETE", authorization, f"/live/leases/{view_id}")
    return Response(status_code=204)
