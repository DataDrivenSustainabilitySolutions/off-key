"""
Data-services API adapter layer.

Routes in this module are intentionally thin: they only parse HTTP inputs,
invoke application services, and map domain errors to HTTP responses.
"""

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...domain import (
    AuthenticationError,
    ConflictError,
    DomainError,
    InfrastructureError,
    NotFoundError,
    ValidationError,
)
from ...provider import (
    get_anomaly_service,
    get_charger_query_service,
    get_favorite_service,
    get_telemetry_query_service,
    get_user_service,
)
from ...schemas import (
    AnomalyCreateRequest,
    AnomalyResponse,
    ChargerResponse,
    FavoriteMutationRequest,
    UserCreateRequest,
    UserLoginRequest,
    UserPasswordUpdateRequest,
    UserResponse,
)
from ...services.data import (
    AnomalyService,
    ChargerQueryService,
    FavoriteService,
    TelemetryQueryService,
    UserService,
)

router = APIRouter()


def _raise_http_from_domain(error: DomainError) -> None:
    """Map domain/application errors to HTTP errors."""
    if isinstance(error, NotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, ConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, AuthenticationError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error))
    if isinstance(error, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        )
    if isinstance(error, InfrastructureError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal infrastructure error",
        )

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unexpected domain error",
    )


@router.get("/chargers", response_model=list[ChargerResponse])
async def get_chargers(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    active_only: bool = Query(False),
    service: ChargerQueryService = Depends(get_charger_query_service),
):
    try:
        return await service.list_chargers(
            skip=skip,
            limit=limit,
            active_only=active_only,
        )
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.get("/chargers/active/ids", response_model=dict)
async def get_active_charger_ids(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    service: ChargerQueryService = Depends(get_charger_query_service),
):
    try:
        return await service.list_active_charger_ids(skip=skip, limit=limit)
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.get("/telemetry/{charger_id}/types", response_model=list[str])
async def get_telemetry_types(
    charger_id: str,
    limit: int = Query(100, ge=1, le=1000),
    service: TelemetryQueryService = Depends(get_telemetry_query_service),
):
    try:
        return await service.list_types(charger_id=charger_id, limit=limit)
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.get("/telemetry/{charger_id}")
async def get_telemetry_data(
    charger_id: str,
    telemetry_type: str = Query(..., alias="type"),
    limit: int = Query(1000, ge=1, le=10000),
    after_timestamp: Optional[datetime] = Query(None),
    paginated: bool = Query(False),
    service: TelemetryQueryService = Depends(get_telemetry_query_service),
) -> list[dict[str, Any]] | dict[str, Any]:
    try:
        return await service.get_telemetry_data(
            charger_id=charger_id,
            telemetry_type=telemetry_type,
            limit=limit,
            after_timestamp=after_timestamp,
            paginated=paginated,
        )
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.post("/auth/login")
async def authenticate_user(
    login_data: UserLoginRequest,
    service: UserService = Depends(get_user_service),
) -> dict[str, str]:
    try:
        return await service.authenticate(
            email=login_data.email,
            password=login_data.password,
        )
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.get("/users/{email}", response_model=UserResponse)
async def get_user_by_email(
    email: str,
    service: UserService = Depends(get_user_service),
) -> dict[str, object]:
    try:
        return await service.get_by_email(email=email)
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.post("/users", response_model=UserResponse)
async def create_user(
    user_data: UserCreateRequest,
    service: UserService = Depends(get_user_service),
):
    try:
        return await service.create_user(payload=user_data)
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.patch("/users/{email}/verify")
async def verify_user_email(
    email: str,
    service: UserService = Depends(get_user_service),
):
    try:
        return await service.verify_email(email=email)
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.patch("/users/{email}/password")
async def update_user_password(
    email: str,
    payload: UserPasswordUpdateRequest,
    service: UserService = Depends(get_user_service),
):
    try:
        return await service.update_password(
            email=email,
            new_password_hash=payload.new_password_hash,
        )
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.get("/users/{user_id}/favorites", response_model=list[str])
async def get_user_favorites(
    user_id: int,
    service: FavoriteService = Depends(get_favorite_service),
):
    try:
        return await service.list_user_favorites(user_id=user_id)
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.post("/users/{user_id}/favorites")
async def add_user_favorite(
    user_id: int,
    payload: FavoriteMutationRequest,
    service: FavoriteService = Depends(get_favorite_service),
):
    try:
        return await service.add_favorite(
            user_id=user_id, charger_id=payload.charger_id
        )
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.delete("/users/{user_id}/favorites/{charger_id}")
async def remove_user_favorite(
    user_id: int,
    charger_id: str,
    service: FavoriteService = Depends(get_favorite_service),
):
    try:
        return await service.remove_favorite(user_id=user_id, charger_id=charger_id)
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.get("/anomalies/count")
async def get_anomaly_count(
    since: Optional[datetime] = Query(None),
    service: AnomalyService = Depends(get_anomaly_service),
):
    try:
        count = await service.count_anomalies(since=since)
        return {"count": count}
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.get("/anomalies/{charger_id}", response_model=list[AnomalyResponse])
async def get_charger_anomalies(
    charger_id: str,
    telemetry_type: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    service: AnomalyService = Depends(get_anomaly_service),
):
    try:
        return await service.list_anomalies(
            charger_id=charger_id,
            telemetry_type=telemetry_type,
            limit=limit,
        )
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.post("/anomalies")
async def create_anomaly(
    anomaly_data: AnomalyCreateRequest,
    service: AnomalyService = Depends(get_anomaly_service),
):
    try:
        return await service.create_anomaly(payload=anomaly_data)
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.delete("/anomalies/{anomaly_id}")
async def delete_anomaly(
    anomaly_id: str,
    service: AnomalyService = Depends(get_anomaly_service),
):
    try:
        return await service.delete_anomaly(anomaly_id=anomaly_id)
    except DomainError as exc:
        _raise_http_from_domain(exc)
