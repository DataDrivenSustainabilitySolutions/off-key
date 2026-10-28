"""Authenticated access to domain-neutral saved system configuration."""

from fastapi import APIRouter, Depends, HTTPException, Request
from off_key_core.db.models import User
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
from off_key_core.utils.enum import RoleEnum

from ...provider import get_broker_check, get_system_service
from ...services.catalogue.broker_check import BrokerCheck
from ...services.catalogue.system import SystemService
from ..collection_auth import current_member, require_admin
from ..errors import DomainErrorRoute
from .system_live import router as live_router

router = APIRouter(prefix="/system", tags=["system"], route_class=DomainErrorRoute)
router.include_router(live_router)


@router.get("/health")
async def collection_health(
    user: User = Depends(current_member),
    system: SystemService = Depends(get_system_service),
):
    return await system.health()


@router.get("/storage", response_model=StorageStatus)
async def storage_status(
    user: User = Depends(current_member),
    system: SystemService = Depends(get_system_service),
):
    return await system.storage()


@router.post("/collection/status")
async def collection_status(
    scope: SystemCollectionScope,
    user: User = Depends(current_member),
    system: SystemService = Depends(get_system_service),
):
    return await system.collection_status(scope.stream_ids)


@router.post("/collection/preview")
async def preview_collection(
    change: SystemCollectionChange | SystemCollectionRuleChange,
    user: User = Depends(require_admin),
    system: SystemService = Depends(get_system_service),
):
    return await system.preview_collection(change)


@router.put("/collection")
async def apply_collection(
    change: SystemCollectionChange | SystemCollectionRuleChange,
    user: User = Depends(require_admin),
    system: SystemService = Depends(get_system_service),
):
    snapshot = await system.apply_collection(change, actor=user.email)
    return {**snapshot.model_dump(mode="json"), "can_edit": True}


@router.post("/connections/check", response_model=SystemConnectionCheck)
async def check_connection(
    scope: SystemConnectionCheckScope,
    user: User = Depends(require_admin),
    system: SystemService = Depends(get_system_service),
    checker: BrokerCheck = Depends(get_broker_check),
):
    """CONNECT once with the saved settings and disconnect; nothing is subscribed."""
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
    return await checker.check(connection)


@router.get("")
async def get_system(
    user: User = Depends(current_member),
    system: SystemService = Depends(get_system_service),
):
    snapshot = await system.read()
    return {**snapshot.model_dump(mode="json"), "can_edit": user.role == RoleEnum.admin}


@router.put("")
async def save_system(
    change: SystemChange,
    request: Request,
    user: User = Depends(require_admin),
    system: SystemService = Depends(get_system_service),
):
    snapshot = await system.save(change, actor=user.email)
    live = getattr(request.app.state, "system_live", None)
    if live is not None:
        await live.reconcile(snapshot)
    return {**snapshot.model_dump(mode="json"), "can_edit": True}


@router.get("/revisions")
async def list_revisions(
    user: User = Depends(current_member),
    system: SystemService = Depends(get_system_service),
):
    return await system.revisions(limit=50)
