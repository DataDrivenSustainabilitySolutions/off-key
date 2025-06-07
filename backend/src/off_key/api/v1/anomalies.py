from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime

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
        }
        for a in anomalies
    ]

@router.post("/")
def create_anomaly(
    charger_id: str,
    timestamp: datetime,
    telemetry_type: str,
    anomaly_type: str,
    db: Session = Depends(get_db_sync)
):
    new_anomaly = Anomaly(
        charger_id=charger_id,
        timestamp=timestamp,
        telemetry_type=telemetry_type,
        anomaly_type=anomaly_type
    )
    db.add(new_anomaly)
    db.commit()
    db.refresh(new_anomaly)
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