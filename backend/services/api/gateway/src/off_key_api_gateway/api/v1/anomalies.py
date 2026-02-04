from fastapi import APIRouter, HTTPException
from datetime import datetime

from off_key_core.utils.mail import send_anomaly_alert_email
from off_key_core.config.logs import logger
from ...facades.tactic import tactic

router = APIRouter()


@router.get("")
async def get_anomalies(charger_id: str, limit: int = 500):
    """Get anomalies for charger via TACTIC data service."""
    try:
        return await tactic.get_charger_anomalies(charger_id=charger_id, limit=limit)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve anomalies: {str(e)}"
        )


@router.post("")
async def create_anomaly(
    charger_id: str,
    timestamp: datetime,
    telemetry_type: str,
    anomaly_type: str,
    anomaly_value: float,
):
    """Create anomaly via TACTIC data service."""
    anomaly_data = {
        "charger_id": charger_id,
        "timestamp": timestamp.isoformat(),
        "telemetry_type": telemetry_type,
        "anomaly_type": anomaly_type,
        "anomaly_value": anomaly_value,
    }

    try:
        # Create anomaly via TACTIC
        result = await tactic.create_anomaly(anomaly_data)

        # Log anomaly detection
        logger.warning(
            f"Anomaly detected and recorded | "
            f"Charger: {charger_id} | Type: {anomaly_type} | "
            f"Telemetry: {telemetry_type} | Value: {anomaly_value}"
        )

        # Send alert email (don't fail if this fails)
        try:
            await send_anomaly_alert_email(anomaly_data)
        except Exception as e:
            logger.error(
                f"Failed to send anomaly alert email for charger {charger_id}: {str(e)}"
            )
            # Don't fail the anomaly creation if email fails

        return result

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to create anomaly: {str(e)}"
        )


@router.delete("")
async def delete_anomaly_by_fields(
    charger_id: str,
    timestamp: datetime,
    telemetry_type: str,
):
    """Delete anomaly via TACTIC data service."""
    try:
        result = await tactic.delete_anomaly(
            charger_id=charger_id,
            timestamp=timestamp,
            telemetry_type=telemetry_type,
        )

        logger.info(
            f"Anomaly deleted | Charger: {charger_id} | "
            f"Telemetry: {telemetry_type} | Timestamp: {timestamp}"
        )

        return result

    except Exception as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=404, detail="Anomaly not found with given parameters"
            )
        raise HTTPException(
            status_code=500, detail=f"Failed to delete anomaly: {str(e)}"
        )
