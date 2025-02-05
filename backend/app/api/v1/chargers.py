from fastapi import APIRouter, Depends
from requests import Session

from backend.app.db.database import SessionLocal
from backend.app.services.chargers_sync import ChargersSyncService

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/sync")
async def sync_items(db: Session = Depends(get_db)):
    service = ChargersSyncService(db)
    await service.sync_chargers()
    return {"status": "successful"}
