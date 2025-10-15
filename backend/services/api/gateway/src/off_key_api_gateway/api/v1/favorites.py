from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from off_key_core.db.base import get_db_async
from off_key_core.db.models import Favorite
from off_key_core.schemas.favorites import FavoriteCreate

router = APIRouter()


@router.get("")
async def get_favorites(user_id: int, db: AsyncSession = Depends(get_db_async)):
    result = await db.execute(select(Favorite).filter(Favorite.user_id == user_id))
    favorites = result.scalars().all()
    return [f.charger_id for f in favorites]


@router.post("")
async def add_favorite(fav: FavoriteCreate, db: AsyncSession = Depends(get_db_async)):
    # Check if already exists
    result = await db.execute(
        select(Favorite).filter(
            Favorite.user_id == fav.user_id, Favorite.charger_id == fav.charger_id
        )
    )
    exists = result.scalars().first()

    if exists:
        raise HTTPException(status_code=400, detail="Charger already favorited")

    new_fav = Favorite(user_id=fav.user_id, charger_id=fav.charger_id)
    db.add(new_fav)
    await db.commit()
    await db.refresh(new_fav)
    return {"message": "Favorite added"}


@router.delete("")
async def remove_favorite(
    fav: FavoriteCreate, db: AsyncSession = Depends(get_db_async)
):
    result = await db.execute(
        select(Favorite).filter(
            Favorite.user_id == fav.user_id, Favorite.charger_id == fav.charger_id
        )
    )
    existing = result.scalars().first()

    if not existing:
        raise HTTPException(status_code=404, detail="Favorite not found")

    await db.delete(existing)
    await db.commit()
    return {"message": "Favorite removed"}
