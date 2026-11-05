from fastapi import APIRouter, Depends, HTTPException, Response
from off_key_core.config.logs import logger
from off_key_core.schemas.members import MemberInvitation, MemberProfile, MemberUpdate
from off_key_core.utils.mail import send_invitation_email

from ...facades.tactic import tactic
from ..access import current_member, member_authorization, require_admin
from ..errors import TacticErrorRoute

router = APIRouter(route_class=TacticErrorRoute)


async def member_request(method, path, authorization, body=None):
    return await tactic.request(
        method,
        f"/api/v1/members{path}",
        json_data=body,
        headers={"Authorization": authorization},
    )


@router.get("/me", response_model=MemberProfile)
async def get_my_profile(user: MemberProfile = Depends(current_member)):
    """The signed-in member: id, email, role and status."""
    return user


@router.get(
    "", response_model=list[MemberProfile], dependencies=[Depends(require_admin)]
)
async def list_members(authorization: str = Depends(member_authorization)):
    """Every member and pending invitation. Administrators only."""
    return await member_request("GET", "", authorization)


@router.post("/invitations", dependencies=[Depends(require_admin)])
async def invite_member(
    invitation: MemberInvitation, authorization: str = Depends(member_authorization)
):
    """Invite an email address with a role and send the invitation email.

    The link expires after 48 hours; inviting a pending address again sends a new one.
    Administrators only.
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


@router.put(
    "/{user_id}", response_model=MemberProfile, dependencies=[Depends(require_admin)]
)
async def update_member(
    user_id: int,
    change: MemberUpdate,
    authorization: str = Depends(member_authorization),
):
    """Change a member's role or disable them. Administrators only.

    The last active administrator cannot be demoted or disabled.
    """
    return await member_request(
        "PUT",
        f"/{user_id}",
        authorization,
        change.model_dump(mode="json"),
    )


@router.delete(
    "/{user_id}",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(require_admin)],
)
async def remove_member(
    user_id: int, authorization: str = Depends(member_authorization)
):
    """Delete a disabled member and their favorites. Administrators only.

    Shared catalogue data, monitors and alarms are kept.
    """
    await member_request("DELETE", f"/{user_id}", authorization)
    return Response(status_code=204)
