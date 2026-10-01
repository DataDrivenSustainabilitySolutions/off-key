"""Authenticated catalog editing and collection status."""

import asyncio
from datetime import UTC, datetime
from importlib.resources import files
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from off_key_core.db.base import get_db_async
from off_key_core.db.collection import read_collection_configuration
from off_key_core.db.models import (
    CollectionConfiguration,
    CollectionRevision,
    CollectionState,
    User,
)
from off_key_core.db.retention import read_storage_status
from off_key_core.schemas.collection import (
    AmbiboxCatalog,
    CatalogChange,
    CatalogPreview,
    CatalogSnapshot,
    SensorActivity,
    SourceProbeRequest,
    SourceProbeResult,
)
from off_key_core.schemas.storage import StorageStatus
from off_key_core.utils.enum import RoleEnum
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config.collection import get_ambibox_settings
from ...domain import DomainError, InfrastructureError
from ...services.collection import CollectionService
from ...services.source_probe import PROBE_SECONDS, probe_source
from ..collection_auth import current_member, require_admin
from .data_services import _raise_http_from_domain

router = APIRouter(prefix="/collection", tags=["collection"])


async def read_sensor_activity(
    session: AsyncSession, revision: int, collection: dict
) -> dict[str, dict[str, SensorActivity]]:
    if collection.get("revision") != revision or collection.get("status") != "applied":
        return {}
    rows = await session.execute(
        select(
            CollectionState.charger_id,
            CollectionState.sensor_key,
            CollectionState.received_at,
            CollectionState.is_snapshot,
        )
    )
    activity = {}
    for charger_id, sensor_key, received_at, is_snapshot in rows:
        activity.setdefault(charger_id, {})[sensor_key] = SensorActivity(
            received_at=received_at, is_snapshot=is_snapshot
        )
    return activity


@router.get("")
async def get_catalog(
    user: User = Depends(current_member),
    session: AsyncSession = Depends(get_db_async),
):
    snapshot = await read_collection_configuration(session)
    snapshot.sensor_activity = await read_sensor_activity(
        session, snapshot.revision, snapshot.collection
    )
    if not get_ambibox_settings().AMBIBOX_INGRESS_ENABLED:
        snapshot.ingress = {
            "status": "disabled",
            "checked_at": datetime.now(UTC).isoformat(),
        }
    return {**snapshot.model_dump(mode="json"), "can_edit": user.role == RoleEnum.admin}


@router.post("/preview", response_model=CatalogPreview)
async def preview_catalog(
    change: CatalogChange,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_async),
):
    try:
        return await CollectionService(session).preview(change)
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.post("/sources/{source_id}/probe", response_model=SourceProbeResult)
async def probe_broker(
    source_id: UUID,
    request: SourceProbeRequest,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_async),
):
    snapshot = await read_collection_configuration(session)
    if request.expected_revision != snapshot.revision:
        raise HTTPException(409, "The catalog changed. Reload before listening.")
    source = next(
        (source for source in snapshot.catalog.sources if source.id == source_id), None
    )
    if source is None:
        raise HTTPException(404, "Broker not found in the saved catalog")
    settings = get_ambibox_settings()
    if not settings.AMBIBOX_INGRESS_ENABLED:
        raise HTTPException(503, "Broker access is disabled by the operator")
    if not settings.allows_host(source.host):
        raise HTTPException(403, "This broker is not allowed by the operator")
    try:
        checked_at = datetime.fromisoformat(snapshot.ingress.get("checked_at", ""))
        fresh = 0 <= (datetime.now(UTC) - checked_at).total_seconds() <= 15
    except (ValueError, TypeError):
        fresh = False
    if (
        source.forward_port is None
        or snapshot.ingress.get("revision") != snapshot.revision
        or snapshot.ingress.get("status") != "applied"
        or not fresh
    ):
        raise HTTPException(409, "Wait for broker setup to finish before listening.")
    try:
        activity = await asyncio.to_thread(probe_source, source, settings)
    except InfrastructureError as exc:
        raise HTTPException(502, str(exc)) from exc
    revision = await session.scalar(
        select(CollectionConfiguration.revision).where(CollectionConfiguration.id == 1)
    )
    if revision != snapshot.revision:
        raise HTTPException(
            409, "The catalog changed while listening. Reload and retry."
        )
    return SourceProbeResult(
        revision=revision, window_seconds=PROBE_SECONDS, sensor_activity=activity
    )


@router.get("/status")
async def get_status(
    user: User = Depends(current_member),
    session: AsyncSession = Depends(get_db_async),
):
    row = (
        await session.execute(
            select(
                CollectionConfiguration.revision,
                CollectionConfiguration.ingress_status,
                CollectionConfiguration.collection_status,
            ).where(CollectionConfiguration.id == 1)
        )
    ).first()
    result = (
        {"revision": row[0], "ingress": row[1], "collection": row[2]}
        if row
        else {
            "revision": 0,
            "ingress": {},
            "collection": {},
        }
    )
    result["sensor_activity"] = await read_sensor_activity(
        session, result["revision"], result["collection"]
    )
    if not get_ambibox_settings().AMBIBOX_INGRESS_ENABLED:
        result["ingress"] = {"status": "disabled"}
    return result


@router.get("/storage", response_model=StorageStatus)
async def get_storage(
    user: User = Depends(current_member),
    session: AsyncSession = Depends(get_db_async),
):
    return await read_storage_status(session)


@router.put("", response_model=CatalogSnapshot)
async def apply_catalog(
    change: CatalogChange,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_async),
):
    try:
        return await CollectionService(session).apply(change, actor=user.email)
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.get("/revisions")
async def list_revisions(
    user: User = Depends(current_member),
    session: AsyncSession = Depends(get_db_async),
):
    rows = await session.scalars(
        select(CollectionRevision)
        .order_by(CollectionRevision.revision.desc())
        .limit(50)
    )
    return [
        {
            "revision": row.revision,
            "updated_at": row.updated_at.isoformat(),
            "updated_by": row.updated_by,
        }
        for row in rows
    ]


@router.get("/ambibox-template", response_model=AmbiboxCatalog)
async def get_ambibox_template(user: User = Depends(current_member)):
    document = (
        files("off_key_tactic_middleware")
        .joinpath("data/ambibox-catalog.json")
        .read_text()
    )
    return AmbiboxCatalog.model_validate_json(document)


@router.get("/revisions/{revision}", response_model=AmbiboxCatalog)
async def get_revision(
    revision: int,
    user: User = Depends(current_member),
    session: AsyncSession = Depends(get_db_async),
):
    row = await session.get(CollectionRevision, revision)
    if row is None:
        raise HTTPException(404, "Catalog revision not found")
    return AmbiboxCatalog.model_validate(row.document)


@router.get("/state/{charger_id}")
async def get_charger_state(
    charger_id: UUID,
    user: User = Depends(current_member),
    session: AsyncSession = Depends(get_db_async),
):
    snapshot = await read_collection_configuration(session)
    if (
        snapshot.collection.get("revision") != snapshot.revision
        or snapshot.collection.get("status") != "applied"
    ):
        return []
    rows = await session.scalars(
        select(CollectionState).where(CollectionState.charger_id == str(charger_id))
    )
    return [
        {
            "sensor_key": row.sensor_key,
            "value": row.value,
            "received_at": row.received_at.isoformat(),
            "is_snapshot": row.is_snapshot,
        }
        for row in rows
    ]
