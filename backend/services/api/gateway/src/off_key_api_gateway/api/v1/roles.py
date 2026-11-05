"""Roles: named sets of permissions that members hold."""

from fastapi import APIRouter, Depends, Path, Response
from off_key_core.auth.permissions import PERMISSION_DESCRIPTIONS, Permission
from off_key_core.schemas.members import (
    PermissionInfo,
    RoleCreate,
    RoleProfile,
    RoleUpdate,
)

from ...facades.tactic import path_segment, tactic
from ..access import member_authorization, require_permission
from ..errors import TacticErrorRoute

router = APIRouter(route_class=TacticErrorRoute)
manage_members = require_permission(Permission.manage_members)
RoleIdPath = Path(description="The role's id, such as `user`.")


async def role_request(method, path, authorization, body=None):
    return await tactic.request(
        method,
        f"/api/v1/roles{path}",
        json_data=body,
        headers={"Authorization": authorization},
    )


@router.get("/permissions", response_model=list[PermissionInfo])
async def list_permissions():
    """Every permission a role can grant. Every member can read everything."""
    return [
        PermissionInfo(id=permission, description=PERMISSION_DESCRIPTIONS[permission])
        for permission in Permission
    ]


@router.get("/roles", response_model=list[RoleProfile])
async def list_roles(authorization: str = Depends(member_authorization)):
    """Every role, its permissions and how many members hold it.

    `admin` always holds every permission and cannot be changed; `user` is the
    role new members get unless an invitation names another.
    """
    return await role_request("GET", "", authorization)


@router.post(
    "/roles",
    response_model=RoleProfile,
    status_code=201,
    dependencies=[Depends(manage_members)],
)
async def create_role(
    change: RoleCreate, authorization: str = Depends(member_authorization)
):
    """Create a role. Its id is derived from the name. Needs `manage_members`."""
    return await role_request("POST", "", authorization, change.model_dump(mode="json"))


@router.patch(
    "/roles/{role_id}",
    response_model=RoleProfile,
    dependencies=[Depends(manage_members)],
)
async def update_role(
    change: RoleUpdate,
    role_id: str = RoleIdPath,
    authorization: str = Depends(member_authorization),
):
    """Rename a role or replace its permissions. Needs `manage_members`.

    Members holding the role gain or lose access on their next request. Refused
    with 409 when no active member could manage members afterwards.
    """
    return await role_request(
        "PATCH",
        f"/{path_segment(role_id)}",
        authorization,
        change.model_dump(mode="json", exclude_unset=True),
    )


@router.delete(
    "/roles/{role_id}",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(manage_members)],
)
async def delete_role(
    role_id: str = RoleIdPath, authorization: str = Depends(member_authorization)
):
    """Delete a role no member holds. Needs `manage_members`.

    `admin` and `user` cannot be deleted.
    """
    await role_request("DELETE", f"/{path_segment(role_id)}", authorization)
    return Response(status_code=204)
