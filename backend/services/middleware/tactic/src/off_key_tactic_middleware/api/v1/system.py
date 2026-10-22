"""Authenticated access to domain-neutral saved system configuration."""

from fastapi import APIRouter, Depends, Request
from off_key_core.db.base import get_db_async
from off_key_core.db.collection_runtime import read_collection_runtime
from off_key_core.db.models import User
from off_key_core.db.retention import read_storage_status
from off_key_core.db.system import SystemRevision
from off_key_core.schemas.collection_rules import SystemCollectionRuleChange
from off_key_core.schemas.storage import StorageStatus
from off_key_core.schemas.system import SystemChange
from off_key_core.schemas.system_collection import (
    SystemCollectionChange,
    SystemCollectionScope,
)
from off_key_core.utils.enum import RoleEnum
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...services.system import SystemService
from ...services.system_collection import SystemCollectionService
from ..collection_auth import current_member, require_admin
from ..errors import DomainErrorRoute
from .system_live import router as live_router

router = APIRouter(prefix="/system", tags=["system"], route_class=DomainErrorRoute)
router.include_router(live_router)


@router.get("/health")
async def collection_health(
    user: User = Depends(current_member),
    session: AsyncSession = Depends(get_db_async),
):
    snapshot = await read_collection_runtime(session)
    return {
        "revision": snapshot.revision,
        "collection": snapshot.collection,
        "ingress": snapshot.ingress,
    }


@router.get("/storage", response_model=StorageStatus)
async def storage_status(
    user: User = Depends(current_member),
    session: AsyncSession = Depends(get_db_async),
):
    return await read_storage_status(session)


@router.post("/collection/status")
async def collection_status(
    scope: SystemCollectionScope,
    user: User = Depends(current_member),
    session: AsyncSession = Depends(get_db_async),
):
    snapshot = await SystemService(session).read()
    wanted = set(scope.stream_ids)
    snapshot.runtime.bindings = {
        key: value for key, value in snapshot.runtime.bindings.items() if key in wanted
    }
    connections = {
        value["connection_id"] for value in snapshot.runtime.bindings.values()
    }
    if "sources" in snapshot.runtime.ingress:
        snapshot.runtime.ingress["sources"] = {
            key: value
            for key, value in snapshot.runtime.ingress["sources"].items()
            if key in connections
        }
    if "readings" in snapshot.runtime.ingress:
        snapshot.runtime.ingress["readings"] = {
            key: value
            for key, value in snapshot.runtime.ingress["readings"].items()
            if key in snapshot.runtime.bindings
        }
    snapshot.runtime.latest_readings = await SystemService(session).latest_readings(
        snapshot.runtime.bindings
    )
    return {
        "revision": snapshot.revision,
        "runtime": snapshot.runtime.model_dump(mode="json"),
    }


@router.post("/collection/preview")
async def preview_collection(
    change: SystemCollectionChange | SystemCollectionRuleChange,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_async),
):
    _, preview = await SystemCollectionService(session).prepare(
        await SystemService(session).read(), change
    )
    return preview


@router.put("/collection")
async def apply_collection(
    change: SystemCollectionChange | SystemCollectionRuleChange,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_async),
):
    snapshot = await SystemCollectionService(session).apply(change, actor=user.email)
    return {**snapshot.model_dump(mode="json"), "can_edit": True}


@router.get("")
async def get_system(
    user: User = Depends(current_member),
    session: AsyncSession = Depends(get_db_async),
):
    snapshot = await SystemService(session).read()
    return {**snapshot.model_dump(mode="json"), "can_edit": user.role == RoleEnum.admin}


@router.put("")
async def save_system(
    change: SystemChange,
    request: Request,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_async),
):
    snapshot = await SystemService(session).save(change, actor=user.email)
    live = getattr(request.app.state, "system_live", None)
    if live is not None:
        await live.reconcile(snapshot)
    return {**snapshot.model_dump(mode="json"), "can_edit": True}


@router.get("/revisions")
async def list_revisions(
    user: User = Depends(current_member),
    session: AsyncSession = Depends(get_db_async),
):
    rows = await session.scalars(
        select(SystemRevision).order_by(SystemRevision.revision.desc()).limit(50)
    )
    return [
        {
            "revision": row.revision,
            "updated_at": row.updated_at.isoformat(),
            "updated_by": row.updated_by,
        }
        for row in rows
    ]
