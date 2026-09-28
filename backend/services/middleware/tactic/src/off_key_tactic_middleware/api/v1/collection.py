"""Authenticated catalog editing and collection status."""

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
)
from off_key_core.schemas.storage import StorageStatus
from off_key_core.utils.enum import RoleEnum
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config.collection import get_ambibox_settings
from ...domain import DomainError
from ...services.collection import CollectionService
from ..collection_auth import collection_admin, collection_user
from .data_services import _raise_http_from_domain

router = APIRouter(prefix="/collection", tags=["collection"])


@router.get("")
async def get_catalog(
    user: User = Depends(collection_user),
    session: AsyncSession = Depends(get_db_async),
):
    snapshot = await read_collection_configuration(session)
    if not get_ambibox_settings().AMBIBOX_INGRESS_ENABLED:
        snapshot.ingress = {
            "status": "disabled",
            "checked_at": datetime.now(UTC).isoformat(),
        }
    return {**snapshot.model_dump(mode="json"), "can_edit": user.role == RoleEnum.admin}


@router.post("/preview", response_model=CatalogPreview)
async def preview_catalog(
    change: CatalogChange,
    user: User = Depends(collection_admin),
    session: AsyncSession = Depends(get_db_async),
):
    try:
        return await CollectionService(session).preview(change)
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.get("/status")
async def get_status(
    user: User = Depends(collection_user),
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
    if not get_ambibox_settings().AMBIBOX_INGRESS_ENABLED:
        result["ingress"] = {"status": "disabled"}
    return result


@router.get("/storage", response_model=StorageStatus)
async def get_storage(
    user: User = Depends(collection_user),
    session: AsyncSession = Depends(get_db_async),
):
    return await read_storage_status(session)


@router.put("", response_model=CatalogSnapshot)
async def apply_catalog(
    change: CatalogChange,
    user: User = Depends(collection_admin),
    session: AsyncSession = Depends(get_db_async),
):
    try:
        return await CollectionService(session).apply(change, actor=user.email)
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.get("/revisions")
async def list_revisions(
    user: User = Depends(collection_user),
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
async def get_ambibox_template(user: User = Depends(collection_user)):
    document = (
        files("off_key_tactic_middleware")
        .joinpath("data/ambibox-catalog.json")
        .read_text()
    )
    return AmbiboxCatalog.model_validate_json(document)


@router.get("/revisions/{revision}", response_model=AmbiboxCatalog)
async def get_revision(
    revision: int,
    user: User = Depends(collection_user),
    session: AsyncSession = Depends(get_db_async),
):
    row = await session.get(CollectionRevision, revision)
    if row is None:
        raise HTTPException(404, "Catalog revision not found")
    return AmbiboxCatalog.model_validate(row.document)


@router.get("/state/{charger_id}")
async def get_charger_state(
    charger_id: UUID,
    user: User = Depends(collection_user),
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
