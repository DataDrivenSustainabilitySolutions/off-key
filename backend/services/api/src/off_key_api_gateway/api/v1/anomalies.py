from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from off_key_core.utils.mail import send_anomaly_alert_email
from off_key_core.db.base import get_db_async
from off_key_core.db.models import Anomaly
from off_key_core.config.logs import logger

router = APIRouter()


@router.get("/")
async def get_anomalies(charger_id: str, db: AsyncSession = Depends(get_db_async)):
    result = await db.execute(
        select(Anomaly)
        .filter(Anomaly.charger_id == charger_id)
        .order_by(Anomaly.timestamp.desc())
        .limit(500)  # Safety limit for anomalies
    )
    anomalies = result.scalars().all()
    return [
        {
            "charger_id": a.charger_id,
            "timestamp": a.timestamp,
            "telemetry_type": a.telemetry_type,
            "anomaly_type": a.anomaly_type,
            "anomaly_value": a.anomaly_value,
        }
        for a in anomalies
    ]


@router.post("/")
async def create_anomaly(
    charger_id: str,
    timestamp: datetime,
    telemetry_type: str,
    anomaly_type: str,
    anomaly_value: float,
    db: AsyncSession = Depends(get_db_async),
):
    new_anomaly = Anomaly(
        charger_id=charger_id,
        timestamp=timestamp,
        telemetry_type=telemetry_type,
        anomaly_type=anomaly_type,
        anomaly_value=anomaly_value,
    )
    db.add(new_anomaly)
    await db.commit()
    await db.refresh(new_anomaly)

    # Log anomaly detection
    logger.warning(
        f"Anomaly detected and recorded | "
        f"Charger: {charger_id} | Type: {anomaly_type} | "
        f"Telemetry: {telemetry_type} | Value: {anomaly_value}"
    )

    try:
        await send_anomaly_alert_email(
            {
                "charger_id": new_anomaly.charger_id,
                "timestamp": new_anomaly.timestamp,
                "telemetry_type": new_anomaly.telemetry_type,
                "anomaly_type": new_anomaly.anomaly_type,
                "anomaly_value": new_anomaly.anomaly_value,
            }
        )
    except Exception as e:
        logger.error(
            f"Failed to send anomaly alert email for charger {charger_id}: {str(e)}"
        )
        # Don't fail the anomaly creation if email fails

    return {"message": "Anomaly added"}


@router.delete("/")
async def delete_anomaly_by_fields(
    charger_id: str,
    timestamp: datetime,
    telemetry_type: str,
    db: AsyncSession = Depends(get_db_async),
):
    result = await db.execute(
        select(Anomaly).filter(
            Anomaly.charger_id == charger_id,
            Anomaly.timestamp == timestamp,
            Anomaly.telemetry_type == telemetry_type,
        )
    )
    anomaly = result.scalars().first()

    if not anomaly:
        raise HTTPException(
            status_code=404, detail="Anomaly not found with given parameters"
        )

    await db.delete(anomaly)
    await db.commit()

    logger.info(
        f"Anomaly deleted | Charger: {charger_id} | "
        f"Type: {anomaly.anomaly_type} | Timestamp: {timestamp}"
    )

    return {"message": "Anomaly deleted successfully"}
