from datetime import datetime

from fastapi import APIRouter, Body, HTTPException, status
from off_key_core.config.logs import logger
from off_key_core.schemas.reporting import AnomalyPage, AnomalyQuery
from off_key_core.utils.mail import send_anomaly_alert_email
from pydantic import BaseModel

from ...facades.tactic import TacticError, tactic
from ..errors import TacticErrorRoute

router = APIRouter(route_class=TacticErrorRoute)
# Reading alarms is open to every member, even though the query is a POST.
query_router = APIRouter(route_class=TacticErrorRoute)


@query_router.post("/query", response_model=AnomalyPage)
async def query_anomalies(query: AnomalyQuery):
    """Alarms of catalogue readings, newest first, with catalogue names.

    Scope by `stream_ids` from `GET /v1/system` and narrow by one recorded
    `reading`, `service_id`, `since`/`until` and `max_p_value`. `summary` and
    `readings` describe every match, not just this page; pass `next` as
    `before` for older alarms. Reporting in the web app uses this query.
    """
    return await tactic.query_anomalies(query.model_dump(mode="json"))


class AnomalyCreatePayload(BaseModel):
    charger_id: str
    timestamp: datetime
    telemetry_type: str
    anomaly_type: str
    anomaly_value: float
    value_type: str | None = None
    sensor_set: list[str] | None = None


@router.get("/count")
async def count_anomalies(since: datetime | None = None):
    """Number of alarms, all of them or those since a time."""
    return await tactic.get_anomaly_count(since=since)


@router.get("")
async def list_anomalies(
    charger_id: str,
    telemetry_type: str | None = None,
    limit: int = 500,
):
    """Alarms of one entity, newest first, optionally for one telemetry type."""
    return await tactic.get_charger_anomalies(
        charger_id=charger_id,
        telemetry_type=telemetry_type,
        limit=limit,
    )


@router.post("")
async def create_anomaly(
    payload: AnomalyCreatePayload | None = Body(default=None),
    charger_id: str | None = None,
    timestamp: datetime | None = None,
    telemetry_type: str | None = None,
    anomaly_type: str | None = None,
    anomaly_value: float | None = None,
    value_type: str | None = None,
    sensor_set: list[str] | None = None,
):
    """Record an alarm by hand and email the configured alert recipients.

    Monitors record their own alarms; this is for external detectors.
    Administrators only.
    """
    if payload is None:
        if (
            charger_id is None
            or timestamp is None
            or telemetry_type is None
            or anomaly_type is None
            or anomaly_value is None
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Either provide JSON body payload or all required query params: "
                    "charger_id, timestamp, telemetry_type, anomaly_type, anomaly_value"
                ),
            )
        payload = AnomalyCreatePayload(
            charger_id=charger_id,
            timestamp=timestamp,
            telemetry_type=telemetry_type,
            anomaly_type=anomaly_type,
            anomaly_value=anomaly_value,
            value_type=value_type,
            sensor_set=sensor_set,
        )

    anomaly_data = {
        "charger_id": payload.charger_id,
        "timestamp": payload.timestamp.isoformat(),
        "telemetry_type": payload.telemetry_type,
        "anomaly_type": payload.anomaly_type,
        "anomaly_value": payload.anomaly_value,
        "value_type": payload.value_type,
        "sensor_set": payload.sensor_set,
    }

    result = await tactic.create_anomaly(anomaly_data)

    # Log anomaly detection
    logger.warning(
        f"Anomaly detected and recorded | "
        f"Charger: {payload.charger_id} | Type: {payload.anomaly_type} | "
        f"Telemetry: {payload.telemetry_type} | Value: {payload.anomaly_value}"
    )

    try:
        await send_anomaly_alert_email(
            {
                "charger_id": payload.charger_id,
                "timestamp": payload.timestamp,
                "telemetry_type": payload.telemetry_type,
                "anomaly_type": payload.anomaly_type,
                "anomaly_value": payload.anomaly_value,
            }
        )
    except Exception as e:
        logger.error(
            f"Failed to send anomaly alert email for charger {payload.charger_id}: "
            f"{e!s}"
        )
        # Don't fail the anomaly creation if email fails

    return result


@router.delete("/{anomaly_id}")
async def delete_anomaly(anomaly_id: str):
    """Remove one alarm by its `anomaly_id`. Administrators only."""
    try:
        result = await tactic.delete_anomaly(anomaly_id=anomaly_id)
    except TacticError as e:
        if e.status == status.HTTP_404_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Anomaly not found",
            ) from e
        raise

    logger.info(f"Anomaly deleted | Anomaly ID: {anomaly_id}")

    return result
