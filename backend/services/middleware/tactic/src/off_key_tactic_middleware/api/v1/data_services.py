"""
Data-services API adapter layer.

Routes in this module are intentionally thin: they only parse HTTP inputs,
invoke application services, and map domain errors to HTTP responses.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from off_key_core.schemas.alarms import (
    Alarm,
    AlarmCount,
    AlarmCreate,
    AlarmDeletionCommit,
    AlarmDeletionPreview,
    AlarmDetail,
    AlarmPage,
    AlarmQuery,
    AlarmSelection,
)
from off_key_core.schemas.favorites import Favorite, FavoriteKind, FavoriteRef

from ...provider import (
    get_alarm_actions,
    get_alarm_service,
    get_favorite_service,
    get_system_service,
    get_user_service,
)
from ...schemas import UserLoginRequest
from ...services.accounts.users import UserService
from ...services.catalogue.system import SystemService
from ...services.data import AlarmService, FavoriteService
from ...services.data.alarm_actions import AlarmActions
from ..errors import DomainErrorRoute

router = APIRouter(route_class=DomainErrorRoute)


@router.post("/auth/login")
async def authenticate_user(
    login_data: UserLoginRequest,
    service: UserService = Depends(get_user_service),
) -> dict[str, object]:
    return await service.authenticate(
        email=login_data.email,
        password=login_data.password,
    )


@router.get("/users/{user_id}/favorites", response_model=list[Favorite])
async def get_user_favorites(
    user_id: int,
    kind: FavoriteKind | None = Query(None),
    service: FavoriteService = Depends(get_favorite_service),
):
    return await service.list_favorites(user_id=user_id, kind=kind)


@router.post("/users/{user_id}/favorites", response_model=Favorite)
async def add_user_favorite(
    user_id: int,
    ref: FavoriteRef,
    service: FavoriteService = Depends(get_favorite_service),
):
    return await service.add_favorite(user_id=user_id, ref=ref)


@router.delete("/users/{user_id}/favorites", status_code=204, response_class=Response)
async def remove_user_favorite(
    user_id: int,
    ref: Annotated[FavoriteRef, Query()],
    service: FavoriteService = Depends(get_favorite_service),
):
    await service.remove_favorite(user_id=user_id, ref=ref)
    return Response(status_code=204)


@router.get("/alarms", response_model=list[Alarm])
async def list_alarms(
    device_id: str | None = Query(None),
    stream_id: list[str] | None = Query(None),
    service_id: str | None = Query(None, min_length=1),
    limit: int = Query(500, ge=1, le=1000),
    service: AlarmService = Depends(get_alarm_service),
    system: SystemService = Depends(get_system_service),
):
    return await service.list_alarms(
        await system.read(),
        device_id=device_id,
        stream_ids=stream_id,
        service_id=service_id,
        limit=limit,
    )


@router.get("/alarms/count", response_model=AlarmCount)
async def count_alarms(
    since: datetime | None = Query(None),
    service: AlarmService = Depends(get_alarm_service),
):
    return AlarmCount(count=await service.count_alarms(since=since))


@router.post("/alarms/query", response_model=AlarmPage)
async def query_alarms(
    query: AlarmQuery,
    service: AlarmService = Depends(get_alarm_service),
    system: SystemService = Depends(get_system_service),
):
    return await service.query(query, await system.read())


@router.post("/alarms", response_model=Alarm, status_code=201)
async def create_alarm(
    alarm: AlarmCreate,
    service: AlarmService = Depends(get_alarm_service),
    system: SystemService = Depends(get_system_service),
):
    return await service.create_alarm(alarm, await system.read())


@router.delete("/alarms/{alarm_id}", status_code=204, response_class=Response)
async def delete_alarm(
    alarm_id: str,
    service: AlarmService = Depends(get_alarm_service),
):
    await service.delete_alarm(alarm_id=alarm_id)
    return Response(status_code=204)


@router.get("/alarms/{alarm_id}", response_model=AlarmDetail)
async def alarm_detail(
    alarm_id: str,
    service: AlarmActions = Depends(get_alarm_actions),
    system: SystemService = Depends(get_system_service),
):
    return await service.detail(alarm_id, await system.read())


@router.post("/alarms/deletion-preview", response_model=AlarmDeletionPreview)
async def preview_alarm_deletion(
    selection: AlarmSelection,
    service: AlarmActions = Depends(get_alarm_actions),
    system: SystemService = Depends(get_system_service),
):
    return await service.preview(selection, await system.read())


@router.post("/alarms/delete", response_model=AlarmCount)
async def delete_alarm_selection(
    selection: AlarmDeletionCommit, service: AlarmActions = Depends(get_alarm_actions)
):
    return AlarmCount(count=await service.delete(selection.token))
