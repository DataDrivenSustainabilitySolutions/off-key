from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String

from ...db.base import get_db_sync, get_db_async
from ...db.models import Favorite
from ...schemas.favorites import FavoriteCreate

router = APIRouter()


@router.get("/")
def get_favorites(user_id: int, db: Session = Depends(get_db_sync)):
    favorites = db.query(Favorite).filter(Favorite.user_id == user_id).all()
    return [f.charger_id for f in favorites]

@router.post("/")
def add_favorite(fav: FavoriteCreate, db: Session = Depends(get_db_sync)):
    # Prüfen, ob bereits existiert
    exists = db.query(Favorite).filter(
        Favorite.user_id == fav.user_id,
        Favorite.charger_id == fav.charger_id
    ).first()

    if exists:
        raise HTTPException(status_code=400, detail="Charger already favorited")

    new_fav = Favorite(user_id=fav.user_id, charger_id=fav.charger_id)
    db.add(new_fav)
    db.commit()
    db.refresh(new_fav)
    return {"message": "Favorite added"}

@router.delete("/")
def remove_favorite(fav: FavoriteCreate, db: Session = Depends(get_db_sync)):
    existing = db.query(Favorite).filter(
        Favorite.user_id == fav.user_id,
        Favorite.charger_id == fav.charger_id
    ).first()

    if not existing:
        raise HTTPException(status_code=404, detail="Favorite not found")

    db.delete(existing)
    db.commit()
    return {"message": "Favorite removed"}