from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime

from ...utils.mail import send_anomaly_alert_email

from ...db.base import get_db_sync
from ...db.models import Anomaly
from ...schemas.anomalies import AnomalyCreate

router = APIRouter()


@router.get("/")
def get_anomalies(charger_id: str, db: Session = Depends(get_db_sync)):
    anomalies = db.query(Anomaly).filter(Anomaly.charger_id == charger_id).all()
    return [
        {
            "charger_id": a.charger_id,
            "timestamp": a.timestamp,
            "telemetry_type": a.telemetry_type,
            "anomaly_type": a.anomaly_type,
            "anomaly_value": a.anomaly_value
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
    db: Session = Depends(get_db_sync)
):
    new_anomaly = Anomaly(
        charger_id=charger_id,
        timestamp=timestamp,
        telemetry_type=telemetry_type,
        anomaly_type=anomaly_type,
        anomaly_value=anomaly_value
    )
    db.add(new_anomaly)
    db.commit()
    db.refresh(new_anomaly)

    await send_anomaly_alert_email({
        "charger_id": new_anomaly.charger_id,
        "timestamp": new_anomaly.timestamp,
        "telemetry_type": new_anomaly.telemetry_type,
        "anomaly_type": new_anomaly.anomaly_type,
        "anomaly_value": new_anomaly.anomaly_value,
    })


    return {"message": "Anomaly added"}

@router.delete("/")
def delete_anomaly_by_fields(
    charger_id: str,
    timestamp: datetime,
    telemetry_type: str,
    db: Session = Depends(get_db_sync)
):
    anomaly = db.query(Anomaly).filter(
        Anomaly.charger_id == charger_id,
        Anomaly.timestamp == timestamp,
        Anomaly.telemetry_type == telemetry_type
    ).first()

    if not anomaly:
        return {"error": "Anomaly not found with given parameters"}
    
    db.delete(anomaly)
    db.commit()
    return {"message": "Anomaly deleted successfully"}