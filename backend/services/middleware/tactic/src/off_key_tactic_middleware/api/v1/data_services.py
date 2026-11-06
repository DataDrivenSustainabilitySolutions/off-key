"""
Data-services API adapter layer.

Routes in this module are intentionally thin: they only parse HTTP inputs,
invoke application services, and map domain errors to HTTP responses.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from off_key_core.schemas.favorites import Favorite, FavoriteKind, FavoriteRef
from off_key_core.schemas.reporting import AnomalyPage, AnomalyQuery

from ...provider import (
    get_anomaly_service,
    get_favorite_service,
    get_system_service,
    get_user_service,
)
from ...schemas import (
    AnomalyCreateRequest,
    AnomalyResponse,
    UserLoginRequest,
)
from ...services.accounts.users import UserService
from ...services.catalogue.system import SystemService
from ...services.data import (
    AnomalyService,
    FavoriteService,
)
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


@router.get("/anomalies/count")
async def get_anomaly_count(
    since: datetime | None = Query(None),
    service: AnomalyService = Depends(get_anomaly_service),
):
    count = await service.count_anomalies(since=since)
    return {"count": count}


@router.post("/anomalies/query", response_model=AnomalyPage)
async def query_anomalies(
    query: AnomalyQuery,
    service: AnomalyService = Depends(get_anomaly_service),
    system: SystemService = Depends(get_system_service),
):
    return await service.query(query, await system.read())


@router.get("/anomalies/{charger_id}", response_model=list[AnomalyResponse])
async def get_charger_anomalies(
    charger_id: str,
    telemetry_type: str | None = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    service: AnomalyService = Depends(get_anomaly_service),
):
    return await service.list_anomalies(
        charger_id=charger_id,
        telemetry_type=telemetry_type,
        limit=limit,
    )


@router.post("/anomalies")
async def create_anomaly(
    anomaly_data: AnomalyCreateRequest,
    service: AnomalyService = Depends(get_anomaly_service),
):
    return await service.create_anomaly(payload=anomaly_data)


@router.delete("/anomalies/{anomaly_id}")
async def delete_anomaly(
    anomaly_id: str,
    service: AnomalyService = Depends(get_anomaly_service),
):
    return await service.delete_anomaly(anomaly_id=anomaly_id)
