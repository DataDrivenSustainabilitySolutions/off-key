"""Authenticated leases control ephemeral generic MQTT workers."""

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from off_key_core.db.base import get_db_async
from off_key_core.db.maintenance import require_application_writes
from off_key_core.db.models import User
from off_key_core.schemas.system_live import SystemLiveScope, SystemLiveStart
from sqlalchemy.ext.asyncio import AsyncSession

from ...services.system import SystemService
from ...services.system_live import LiveSessionError, SystemLiveService
from ..collection_auth import current_member, require_admin

router = APIRouter(prefix="/live", tags=["system-live"])


def live_service(request: Request) -> SystemLiveService:
    service = getattr(request.app.state, "system_live", None)
    if service is None:
        raise HTTPException(503, "Live observation is unavailable.")
    return service


@router.get("")
async def get_live(
    after_sequence: int = Query(default=0, ge=0),
    user: User = Depends(current_member),
    session: AsyncSession = Depends(get_db_async),
    service: SystemLiveService = Depends(live_service),
):
    await service.reconcile(await SystemService(session).read())
    return service.snapshot(after_sequence)


@router.post("/leases")
async def start_live(
    change: SystemLiveStart,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_async),
    service: SystemLiveService = Depends(live_service),
):
    await require_application_writes(session)
    try:
        return await service.acquire(
            await SystemService(session).read(),
            user.id,
            change.expected_revision,
            change.stream_ids,
        )
    except LiveSessionError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.put("/leases/{lease_id}")
async def renew_live(
    change: SystemLiveScope | None = None,
    lease_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_async),
    service: SystemLiveService = Depends(live_service),
):
    await require_application_writes(session)
    try:
        return await service.renew(
            await SystemService(session).read(),
            user.id,
            lease_id,
            change.stream_ids if change else None,
        )
    except LiveSessionError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.delete("/leases/{lease_id}", status_code=204)
async def stop_live(
    lease_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    user: User = Depends(require_admin),
    service: SystemLiveService = Depends(live_service),
):
    try:
        await service.release(user.id, lease_id)
    except LiveSessionError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return Response(status_code=204)
