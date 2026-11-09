from typing import Annotated

from aberration_core.schemas.favorites import Favorite, FavoriteKind, FavoriteRef
from aberration_core.schemas.members import MemberProfile
from fastapi import APIRouter, Depends, Query, Response

from ...facades.tactic import tactic
from ..access import current_member
from ..errors import TacticErrorRoute

router = APIRouter(route_class=TacticErrorRoute)


@router.get("", response_model=list[Favorite])
async def list_favorites(
    kind: FavoriteKind | None = Query(None, description="Only favorites of this kind"),
    user: MemberProfile = Depends(current_member),
):
    """The signed-in member's favorites, oldest first."""
    return await tactic.list_favorites(user_id=user.id, kind=kind)


@router.post("", response_model=Favorite)
async def add_favorite(ref: FavoriteRef, user: MemberProfile = Depends(current_member)):
    """Star a device, reading or monitor for the signed-in member.

    Adding a favorite the member already has returns it unchanged. 409 when the
    member already keeps the maximum of 256.
    """
    return await tactic.add_favorite(user_id=user.id, ref=ref)


@router.delete("", status_code=204, response_class=Response)
async def remove_favorite(
    ref: Annotated[FavoriteRef, Query()],
    user: MemberProfile = Depends(current_member),
):
    """Remove a favorite. Removing one the member does not have also answers 204."""
    await tactic.remove_favorite(user_id=user.id, ref=ref)
    return Response(status_code=204)
