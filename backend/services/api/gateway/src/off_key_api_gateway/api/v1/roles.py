"""Roles: named sets of permissions that members hold."""

from fastapi import APIRouter, Depends, Path, Response
from off_key_core.auth.permissions import PERMISSION_DESCRIPTIONS, Permission
from off_key_core.db.models import User
from off_key_core.schemas.members import (
    PermissionInfo,
    RoleCreate,
    RoleProfile,
    RoleUpdate,
)
from off_key_tactic_middleware.services.accounts.members import MemberService

from ...providers import get_member_service
from ..access import require_permission
from ..errors import DomainErrorRoute

router = APIRouter(route_class=DomainErrorRoute)
manage_members = require_permission(Permission.manage_members)
RoleIdPath = Path(description="The role's id, such as `user`.")


@router.get("/permissions", response_model=list[PermissionInfo])
async def list_permissions():
    """Every permission a role can grant. Reads never need one."""
    return [
        PermissionInfo(id=permission, description=PERMISSION_DESCRIPTIONS[permission])
        for permission in Permission
    ]


@router.get("/roles", response_model=list[RoleProfile])
async def list_roles(service: MemberService = Depends(get_member_service)):
    """Every role, its permissions and how many members hold it.

    `admin` always holds every permission and cannot be changed; `user` is the
    role new members get unless an invitation names another.
    """
    return await service.list_roles()


@router.post("/roles", response_model=RoleProfile, status_code=201)
async def create_role(
    change: RoleCreate,
    actor: User = Depends(manage_members),
    service: MemberService = Depends(get_member_service),
):
    """Create a role. Its id is derived from the name. Needs `manage_members`."""
    return await service.create_role(change, actor)


@router.patch("/roles/{role_id}", response_model=RoleProfile)
async def update_role(
    change: RoleUpdate,
    role_id: str = RoleIdPath,
    actor: User = Depends(manage_members),
    service: MemberService = Depends(get_member_service),
):
    """Rename a role or replace its permissions. Needs `manage_members`.

    Members holding the role gain or lose access on their next request. Refused
    with 409 when no active member could manage members afterwards.
    """
    return await service.update_role(role_id, change, actor)


@router.delete("/roles/{role_id}", status_code=204, response_class=Response)
async def delete_role(
    role_id: str = RoleIdPath,
    actor: User = Depends(manage_members),
    service: MemberService = Depends(get_member_service),
):
    """Delete a role no member holds. Needs `manage_members`.

    `admin` and `user` cannot be deleted.
    """
    await service.delete_role(role_id, actor)
    return Response(status_code=204)
