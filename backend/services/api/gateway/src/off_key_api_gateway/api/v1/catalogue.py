"""The catalogue, its recording, brokers, storage and live views.

Changes need `manage_sources`. Answers carry the public field names.
"""

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from off_key_core.auth.permissions import Permission
from off_key_core.db.models import User
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
from off_key_tactic_middleware.services.catalogue.broker_check import BrokerCheck
from off_key_tactic_middleware.services.catalogue.system import SystemService
from off_key_tactic_middleware.services.catalogue.system_live import (
    LiveSessionError,
    SystemLiveService,
)
from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema

from ...providers import get_broker_check, get_live_service, get_system_service
from ..access import current_member, require_permission
from ..errors import DomainErrorRoute

router = APIRouter(route_class=DomainErrorRoute)
brokers_router = APIRouter(route_class=DomainErrorRoute)
recording_router = APIRouter(route_class=DomainErrorRoute)
storage_router = APIRouter(route_class=DomainErrorRoute)
live_router = APIRouter(route_class=DomainErrorRoute)
manage_sources = require_permission(Permission.manage_sources)

VIEW_ID = Path(pattern=r"^[0-9a-f]{32}$")


class _Open(BaseModel):
    """An answer whose other fields pass through unchanged."""

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
    # How the reading is stored; the API names readings by id only.
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


def _catalogue(snapshot, *, can_edit: bool) -> dict:
    return {**snapshot.model_dump(mode="json"), "can_edit": can_edit}


@router.get("", response_model=Catalogue)
async def get_catalogue(
    request: Request,
    user: User = Depends(current_member),
    system: SystemService = Depends(get_system_service),
):
    """The saved catalogue and how it is recorded now.

    `document` holds `brokers`, `devices`, `readings` and `groups`; `revision`
    is the value to send as `expected_revision` when saving;
    `runtime.bindings` says per reading id how it is recorded;
    `can_edit` says whether the caller may change it.
    """
    result = _catalogue(
        await system.read(),
        can_edit=Permission.manage_sources in user.permissions,
    )
    if getattr(request.state, "demo_guest", False):
        result = {**result, "updated_by": None, "can_edit": False}
    return result


@router.put("", response_model=Catalogue)
async def save_catalogue(
    change: SystemChange,
    request: Request,
    user: User = Depends(manage_sources),
    system: SystemService = Depends(get_system_service),
):
    """Replace the saved catalogue. Needs `manage_sources`.

    Send the whole `document` with the `revision` you read as
    `expected_revision`; a stale revision answers 409. A change to readings
    that running monitors use answers 409 unless `pause_affected_monitors` is
    set, which pauses those monitors first.
    """
    snapshot = await system.save(change, actor=user.email)
    live = getattr(request.app.state, "system_live", None)
    if live is not None:
        await live.reconcile(snapshot)
    return _catalogue(snapshot, can_edit=True)


@router.get("/revisions")
async def list_catalogue_revisions(
    user: User = Depends(current_member),
    system: SystemService = Depends(get_system_service),
):
    """The last 50 saved catalogue revisions, newest first, with who saved them."""
    return await system.revisions(limit=50)


@brokers_router.post("/check", response_model=SystemConnectionCheck)
async def check_broker(
    scope: SystemConnectionCheckScope,
    user: User = Depends(manage_sources),
    system: SystemService = Depends(get_system_service),
    checker: BrokerCheck = Depends(get_broker_check),
):
    """Connect once to a saved broker and disconnect; nothing is subscribed.

    A broker is sent one MQTT CONNECT, an HTTP source one GET for the request
    path of its first reading. Needs `manage_sources`.
    """
    snapshot = await system.read()
    connection = next(
        (
            item
            for item in snapshot.document.connections
            if item.id == scope.connection_id
        ),
        None,
    )
    if connection is None:
        raise HTTPException(404, "This broker is not in the saved system.")
    path = next(
        (
            stream.topic
            for stream in snapshot.document.streams
            if connection.protocol == "http" and stream.connection_id == connection.id
        ),
        None,
    )
    return await checker.check(connection, path=path)


@brokers_router.post("/{broker_id}/reconnect", response_model=BrokerReconnect)
async def reconnect_broker(
    broker_id: str = Path(min_length=1, max_length=280),
    user: User = Depends(manage_sources),
    system: SystemService = Depends(get_system_service),
):
    """Retry a recorded broker now instead of waiting for its backoff.

    Needs `manage_sources`.
    """
    if not await system.request_reconnect(broker_id):
        raise HTTPException(409, "No readings are being recorded from this broker.")
    return {"connection_id": broker_id}


@recording_router.put("", response_model=Catalogue)
async def change_recording(
    change: SystemCollectionChange | SystemCollectionRuleChange,
    user: User = Depends(manage_sources),
    system: SystemService = Depends(get_system_service),
):
    """Change which readings are recorded and how. Needs `manage_sources`.

    Either set one `policy` for `reading_ids`, or send `rule_changes` for a
    broker, topic or reading scope. Affected monitors answer 409 unless
    `pause_affected_monitors` is set. Answers with the saved catalogue.
    """
    snapshot = await system.apply_collection(change, actor=user.email)
    return _catalogue(snapshot, can_edit=True)


@recording_router.post("/preview", response_model=RecordingPreview)
async def preview_recording(
    change: SystemCollectionChange | SystemCollectionRuleChange,
    user: User = Depends(manage_sources),
    system: SystemService = Depends(get_system_service),
):
    """Preview a recording change without applying it. Needs `manage_sources`.

    Answers how many readings would start, stop or change rate, the expected
    rows per day and the running monitors the change would affect.
    """
    return await system.preview_collection(change)


@recording_router.post("/status", response_model=RecordingStatus)
async def get_recording_status(
    scope: SystemCollectionScope,
    user: User = Depends(current_member),
    system: SystemService = Depends(get_system_service),
):
    """Recording state of the given `reading_ids` and their brokers."""
    return await system.collection_status(scope.stream_ids)


@recording_router.get("/health", response_model=CollectionHealth)
async def get_recording_health(
    user: User = Depends(current_member),
    system: SystemService = Depends(get_system_service),
):
    """Whether readings are being recorded, and what to fix if not.

    `diagnosis` names the first failing check (`code`, `tone`, `title`,
    `explanation`) so a caller needs no rules of its own. The raw collector and
    broker reports it was decided from are included for detail views.
    """
    return await system.health()


@storage_router.get("", response_model=StorageStatus)
async def get_storage(
    user: User = Depends(current_member),
    system: SystemService = Depends(get_system_service),
):
    """Database size, retention policies and the storage cap."""
    return await system.storage()


@live_router.get("/measurements", response_model=LiveMeasurements)
async def list_live_measurements(
    after_sequence: int = Query(default=0, ge=0),
    user: User = Depends(current_member),
    system: SystemService = Depends(get_system_service),
    live: SystemLiveService = Depends(get_live_service),
):
    """Latest values from open live views, after the given sequence number."""
    await live.reconcile(await system.read())
    return live.snapshot(after_sequence)


@live_router.post("/views", response_model=LiveView)
async def open_live_view(
    change: SystemLiveStart,
    user: User = Depends(manage_sources),
    system: SystemService = Depends(get_system_service),
    live: SystemLiveService = Depends(get_live_service),
):
    """Watch configured readings live without recording them.

    The view ends on its own unless it is renewed while needed. Nothing is
    stored. Needs `manage_sources`.
    """
    await system.require_writes()
    try:
        return await live.acquire(
            await system.read(),
            user.id,
            change.expected_revision,
            change.stream_ids,
        )
    except LiveSessionError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@live_router.post("/views/{view_id}/renew", response_model=LiveView)
async def renew_live_view(
    view_id: str = VIEW_ID,
    change: SystemLiveScope | None = None,
    user: User = Depends(manage_sources),
    system: SystemService = Depends(get_system_service),
    live: SystemLiveService = Depends(get_live_service),
):
    """Keep a live view open, optionally with other `reading_ids`.

    Needs `manage_sources`.
    """
    await system.require_writes()
    try:
        return await live.renew(
            await system.read(),
            user.id,
            view_id,
            change.stream_ids if change else None,
        )
    except LiveSessionError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@live_router.delete("/views/{view_id}", status_code=204)
async def close_live_view(
    view_id: str = VIEW_ID,
    user: User = Depends(manage_sources),
    live: SystemLiveService = Depends(get_live_service),
):
    """End a live view. Needs `manage_sources`."""
    try:
        await live.release(user.id, view_id)
    except LiveSessionError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return Response(status_code=204)
