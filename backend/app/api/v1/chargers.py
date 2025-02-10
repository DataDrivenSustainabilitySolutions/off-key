from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db.base import SessionLocal
from ...db.models import Chargers
from ...services.chargers_sync import ChargersSyncService

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
    service = ChargersSyncService(db)
    await service.sync_chargers()
    return {"status": "successful"}


@router.get("/active")
async def get_active_chargers(db: Session = Depends(get_db)):
    return db.query(Chargers).filter(Chargers.online).all()


@router.get("/active/id")
async def get_active_charger_ids(db: Session = Depends(get_db)):
    active_ids = db.query(Chargers.charger_id).filter(Chargers.online).all()
    return {"active": [active_id[0] for active_id in active_ids]}
