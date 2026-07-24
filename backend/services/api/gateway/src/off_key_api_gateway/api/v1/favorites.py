from fastapi import APIRouter, HTTPException, status
from off_key_core.schemas.favorites import FavoriteCreate

from ...facades.tactic import TacticError, tactic
from ..errors import raise_tactic_http_error

router = APIRouter()


@router.get("")
async def get_favorites(user_id: int):
    """Get user favorites via TACTIC data service."""
    try:
        return await tactic.get_user_favorites(user_id=user_id)
    except TacticError as e:
        raise_tactic_http_error(e)


@router.post("")
async def add_favorite(fav: FavoriteCreate):
    """Add user favorite via TACTIC data service."""
    try:
        return await tactic.add_user_favorite(
            user_id=fav.user_id, charger_id=fav.charger_id
        )
    except TacticError as e:
        if e.status in (status.HTTP_400_BAD_REQUEST, status.HTTP_409_CONFLICT):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Charger already favorited",
            ) from e
        raise_tactic_http_error(e)


@router.delete("")
async def remove_favorite(fav: FavoriteCreate):
    """Remove user favorite via TACTIC data service."""
    try:
        return await tactic.remove_user_favorite(
            user_id=fav.user_id, charger_id=fav.charger_id
        )
    except TacticError as e:
        if e.status == status.HTTP_404_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Favorite not found",
            ) from e
        raise_tactic_http_error(e)
