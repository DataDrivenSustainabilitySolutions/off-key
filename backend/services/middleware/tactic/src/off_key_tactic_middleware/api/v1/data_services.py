"""
Data-services API adapter layer.

Routes in this module are intentionally thin: they only parse HTTP inputs,
invoke application services, and map domain errors to HTTP responses.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...domain import ValidationError
from ...provider import (
    get_anomaly_service,
    get_charger_query_service,
    get_favorite_service,
    get_monitoring_evidence_service,
    get_telemetry_query_service,
    get_user_service,
)
from ...schemas import (
    AnomalyCreateRequest,
    AnomalyResponse,
    ChargerResponse,
    FavoriteMutationRequest,
    MonitoringChartEvidenceResponse,
    MonitoringEvidenceResponse,
    TelemetryDataPoint,
    TelemetryPaginatedResponse,
    UserLoginRequest,
)
from ...services.data import (
    AnomalyService,
    ChargerQueryService,
    FavoriteService,
    MonitoringEvidenceService,
    TelemetryQueryService,
    UserService,
)
from ..errors import DomainErrorRoute

router = APIRouter(route_class=DomainErrorRoute)


@router.get("/chargers", response_model=list[ChargerResponse])
async def get_chargers(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    active_only: bool = Query(False),
    service: ChargerQueryService = Depends(get_charger_query_service),
):
    return await service.list_chargers(
        skip=skip,
        limit=limit,
        active_only=active_only,
    )


@router.get("/chargers/active/ids", response_model=dict)
async def get_active_charger_ids(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    service: ChargerQueryService = Depends(get_charger_query_service),
):
    return await service.list_active_charger_ids(skip=skip, limit=limit)


@router.get("/telemetry/{charger_id}/types", response_model=list[str])
async def get_telemetry_types(
    charger_id: str,
    limit: int = Query(100, ge=1, le=1000),
    service: TelemetryQueryService = Depends(get_telemetry_query_service),
):
    return await service.list_types(charger_id=charger_id, limit=limit)


@router.get(
    "/telemetry/{charger_id}",
    response_model=list[TelemetryDataPoint] | TelemetryPaginatedResponse,
)
async def get_telemetry_data(
    charger_id: str,
    telemetry_type: str = Query(..., alias="type"),
    limit: int = Query(1000, ge=1, le=10000),
    after_timestamp: datetime | None = Query(None),
    after_created: datetime | None = Query(None),
    after_event_timestamp: datetime | None = Query(None),
    paginated: bool = Query(False),
    service: TelemetryQueryService = Depends(get_telemetry_query_service),
) -> list[TelemetryDataPoint] | TelemetryPaginatedResponse:
    cursor_values = (after_created, after_event_timestamp)
    if any(value is not None for value in cursor_values) and not all(
        value is not None for value in cursor_values
    ):
        raise ValidationError("All telemetry live cursor fields are required")
    if after_timestamp is not None and after_created is not None:
        raise ValidationError(
            "Historical and live telemetry cursors cannot be used together"
        )
    return await service.get_telemetry_data(
        charger_id=charger_id,
        telemetry_type=telemetry_type,
        limit=limit,
        after_timestamp=after_timestamp,
        after_created=after_created,
        after_event_timestamp=after_event_timestamp,
        paginated=paginated,
    )


@router.post("/auth/login")
async def authenticate_user(
    login_data: UserLoginRequest,
    service: UserService = Depends(get_user_service),
) -> dict[str, object]:
    return await service.authenticate(
        email=login_data.email,
        password=login_data.password,
    )


@router.get("/users/{user_id}/favorites", response_model=list[str])
async def get_user_favorites(
    user_id: int,
    service: FavoriteService = Depends(get_favorite_service),
):
    return await service.list_user_favorites(user_id=user_id)


@router.post("/users/{user_id}/favorites")
async def add_user_favorite(
    user_id: int,
    payload: FavoriteMutationRequest,
    service: FavoriteService = Depends(get_favorite_service),
):
    return await service.add_favorite(user_id=user_id, charger_id=payload.charger_id)


@router.delete("/users/{user_id}/favorites/{charger_id}")
async def remove_user_favorite(
    user_id: int,
    charger_id: str,
    service: FavoriteService = Depends(get_favorite_service),
):
    return await service.remove_favorite(user_id=user_id, charger_id=charger_id)


@router.get("/anomalies/count")
async def get_anomaly_count(
    since: datetime | None = Query(None),
    service: AnomalyService = Depends(get_anomaly_service),
):
    count = await service.count_anomalies(since=since)
    return {"count": count}


@router.get(
    "/monitoring-evidence/{charger_id}",
    response_model=list[MonitoringEvidenceResponse],
)
async def get_monitoring_evidence(
    charger_id: str,
    telemetry_type: str | None = Query(None),
    limit: int = Query(2000, ge=1, le=10000),
    service: MonitoringEvidenceService = Depends(get_monitoring_evidence_service),
):
    return await service.list_evidence(
        charger_id=charger_id,
        telemetry_type=telemetry_type,
        limit=limit,
    )


@router.get(
    "/monitoring-evidence/{charger_id}/chart",
    response_model=list[MonitoringChartEvidenceResponse],
)
async def get_monitoring_chart_evidence(
    charger_id: str,
    service_id: str | None = Query(None, min_length=1, max_length=128),
    after_created: datetime | None = Query(None),
    after_timestamp: datetime | None = Query(None),
    after_service_id: str | None = Query(None),
    after_sequence_number: int | None = Query(None, ge=1),
    limit: int = Query(2000, ge=1, le=10000),
    service: MonitoringEvidenceService = Depends(get_monitoring_evidence_service),
):
    cursor_values = (
        after_created,
        after_timestamp,
        after_service_id,
        after_sequence_number,
    )
    if any(value is not None for value in cursor_values) and not all(
        value is not None for value in cursor_values
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="All monitoring evidence cursor fields are required together",
        )
    return await service.list_chart_evidence(
        charger_id=charger_id,
        service_id=service_id,
        after_created=after_created,
        after_timestamp=after_timestamp,
        after_service_id=after_service_id,
        after_sequence_number=after_sequence_number,
        limit=limit,
    )


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
