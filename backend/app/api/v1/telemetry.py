from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db.base import SessionLocal
from ...services.telemetry_sync import TelemetrySyncService

router = APIRouter()


# Dependency for database sessions
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/sync")
async def sync_chargers(db: Session = Depends(get_db)):
    service = TelemetrySyncService(db)
    await service.sync_telemetry()
    return {"status": "successful"}
