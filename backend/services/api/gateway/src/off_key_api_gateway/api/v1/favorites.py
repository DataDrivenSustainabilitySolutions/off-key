from fastapi import APIRouter, HTTPException

from off_key_core.schemas.favorites import FavoriteCreate
from ...facades.tactic import tactic

router = APIRouter()


@router.get("")
async def get_favorites(user_id: int):
    """Get user favorites via TACTIC data service."""
    try:
        return await tactic.get_user_favorites(user_id=user_id)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve favorites: {str(e)}"
        )


@router.post("")
async def add_favorite(fav: FavoriteCreate):
    """Add user favorite via TACTIC data service."""
    try:
        return await tactic.add_user_favorite(
            user_id=fav.user_id, charger_id=fav.charger_id
        )
    except Exception as e:
        if "already favorited" in str(e).lower():
            raise HTTPException(status_code=400, detail="Charger already favorited")
        raise HTTPException(
            status_code=500, detail=f"Failed to add favorite: {str(e)}"
        )


@router.delete("")
async def remove_favorite(fav: FavoriteCreate):
    """Remove user favorite via TACTIC data service."""
    try:
        return await tactic.remove_user_favorite(
            user_id=fav.user_id, charger_id=fav.charger_id
        )
    except Exception as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail="Favorite not found")
        raise HTTPException(
            status_code=500, detail=f"Failed to remove favorite: {str(e)}"
        )
