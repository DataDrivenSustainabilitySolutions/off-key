from typing import Optional

from fastapi import APIRouter, Body, HTTPException, status
from datetime import datetime
from pydantic import BaseModel

from off_key_core.utils.mail import send_anomaly_alert_email
from off_key_core.config.logs import logger
from ...facades.tactic import TacticError, tactic

router = APIRouter()


class AnomalyCreatePayload(BaseModel):
    charger_id: str
    timestamp: datetime
    telemetry_type: str
    anomaly_type: str
    anomaly_value: float


def _get_tactic_error_detail(error: TacticError) -> str:
    """Extract API detail from TACTIC error body when available."""
    if isinstance(error.body, dict):
        detail = error.body.get("detail")
        if detail:
            return str(detail)
    return str(error)


def _raise_tactic_http_error(error: TacticError) -> None:
    raise HTTPException(
        status_code=error.status or status.HTTP_502_BAD_GATEWAY,
        detail=_get_tactic_error_detail(error),
    )


@router.get("")
async def get_anomalies(
    charger_id: str,
    telemetry_type: Optional[str] = None,
    limit: int = 500,
):
    try:
        return await tactic.get_charger_anomalies(
            charger_id=charger_id,
            telemetry_type=telemetry_type,
            limit=limit,
        )
    except TacticError as e:
        _raise_tactic_http_error(e)


@router.post("")
async def create_anomaly(
    payload: AnomalyCreatePayload | None = Body(default=None),
    charger_id: str | None = None,
    timestamp: datetime | None = None,
    telemetry_type: str | None = None,
    anomaly_type: str | None = None,
    anomaly_value: float | None = None,
):
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
        )

    anomaly_data = {
        "charger_id": payload.charger_id,
        "timestamp": payload.timestamp.isoformat(),
        "telemetry_type": payload.telemetry_type,
        "anomaly_type": payload.anomaly_type,
        "anomaly_value": payload.anomaly_value,
    }

    try:
        result = await tactic.create_anomaly(anomaly_data)
    except TacticError as e:
        _raise_tactic_http_error(e)

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
            f"{str(e)}"
        )
        # Don't fail the anomaly creation if email fails

    return result


@router.delete("/{anomaly_id}")
async def delete_anomaly(anomaly_id: str):
    try:
        result = await tactic.delete_anomaly(anomaly_id=anomaly_id)
    except TacticError as e:
        if e.status == status.HTTP_404_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Anomaly not found",
            )
        _raise_tactic_http_error(e)

    logger.info(f"Anomaly deleted | Anomaly ID: {anomaly_id}")

    return result
