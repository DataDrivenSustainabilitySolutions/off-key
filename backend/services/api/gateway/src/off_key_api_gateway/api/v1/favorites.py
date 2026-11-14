from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from off_key_core.db.models import User
from off_key_core.schemas.favorites import Favorite, FavoriteKind, FavoriteRef
from off_key_tactic_middleware.services.data import FavoriteService

from ...providers import get_favorite_service
from ..access import current_member
from ..errors import DomainErrorRoute

router = APIRouter(route_class=DomainErrorRoute)


@router.get("", response_model=list[Favorite])
async def list_favorites(
    kind: FavoriteKind | None = Query(None, description="Only favorites of this kind"),
    user: User = Depends(current_member),
    service: FavoriteService = Depends(get_favorite_service),
):
    """The signed-in member's favorites, oldest first."""
    return await service.list_favorites(user_id=user.id, kind=kind)


@router.post("", response_model=Favorite)
async def add_favorite(
    ref: FavoriteRef,
    user: User = Depends(current_member),
    service: FavoriteService = Depends(get_favorite_service),
):
    """Star a device, reading or monitor for the signed-in member.

    Adding a favorite the member already has returns it unchanged. 409 when the
    member already keeps the maximum of 256.
    """
    return await service.add_favorite(user_id=user.id, ref=ref)


@router.delete("", status_code=204, response_class=Response)
async def remove_favorite(
    ref: Annotated[FavoriteRef, Query()],
    user: User = Depends(current_member),
    service: FavoriteService = Depends(get_favorite_service),
):
    """Remove a favorite. Removing one the member does not have also answers 204."""
    await service.remove_favorite(user_id=user.id, ref=ref)
    return Response(status_code=204)
