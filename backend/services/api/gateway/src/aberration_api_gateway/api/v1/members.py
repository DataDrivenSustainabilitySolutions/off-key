from aberration_core.auth.permissions import Permission
from aberration_core.config.logs import logger
from aberration_core.schemas.members import (
    MemberInvitation,
    MemberProfile,
    MemberUpdate,
)
from aberration_core.utils.mail import send_invitation_email
from fastapi import APIRouter, Depends, HTTPException, Response

from ...facades.tactic import tactic
from ..access import current_member, member_authorization, require_permission
from ..errors import TacticErrorRoute

router = APIRouter(route_class=TacticErrorRoute)
me_router = APIRouter(route_class=TacticErrorRoute)
invitations_router = APIRouter(route_class=TacticErrorRoute)
manage_members = require_permission(Permission.manage_members)


async def member_request(method, path, authorization, body=None):
    return await tactic.request(
        method,
        f"/api/v1/members{path}",
        json_data=body,
        headers={"Authorization": authorization},
    )


@me_router.get("", response_model=MemberProfile)
async def get_me(user: MemberProfile = Depends(current_member)):
    """The signed-in member: id, email, role, permissions and status."""
    return user


@router.get(
    "", response_model=list[MemberProfile], dependencies=[Depends(manage_members)]
)
async def list_members(authorization: str = Depends(member_authorization)):
    """Every member and pending invitation. Needs `manage_members`."""
    return await member_request("GET", "", authorization)


@invitations_router.post("", dependencies=[Depends(manage_members)])
async def create_invitation(
    invitation: MemberInvitation, authorization: str = Depends(member_authorization)
):
    """Invite an email address with a role and send the invitation email.

    The link expires after 48 hours; inviting a pending address again sends a new one.
    Needs `manage_members`.
    """
    result = await member_request(
        "POST",
        "/invitations",
        authorization,
        invitation.model_dump(mode="json"),
    )
    try:
        await send_invitation_email(result["email"], result["token"])
    except Exception:
        logger.error("event=member_invitation_delivery_failed")
        raise HTTPException(
            502, "Invitation saved, but email delivery failed. Check SMTP and resend."
        ) from None
    return {"message": "Invitation sent. The link expires in 48 hours."}


@router.patch(
    "/{member_id}",
    response_model=MemberProfile,
    dependencies=[Depends(manage_members)],
)
async def update_member(
    member_id: int,
    change: MemberUpdate,
    authorization: str = Depends(member_authorization),
):
    """Change a member's `role`, set `is_active`, or both. Needs `manage_members`.

    Fields left out keep their value. Refused with 409 when no active member
    could manage members afterwards.
    """
    return await member_request(
        "PATCH",
        f"/{member_id}",
        authorization,
        change.model_dump(mode="json", exclude_unset=True),
    )


@router.delete(
    "/{member_id}",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(manage_members)],
)
async def remove_member(
    member_id: int, authorization: str = Depends(member_authorization)
):
    """Delete a disabled member and their favorites. Needs `manage_members`.

    Shared catalogue data, monitors and alarms are kept.
    """
    await member_request("DELETE", f"/{member_id}", authorization)
    return Response(status_code=204)
