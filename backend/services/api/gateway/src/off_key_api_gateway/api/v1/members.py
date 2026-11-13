from fastapi import APIRouter, Depends, HTTPException, Response
from off_key_core.auth.permissions import Permission
from off_key_core.config.logs import logger
from off_key_core.db.models import User
from off_key_core.schemas.members import MemberInvitation, MemberProfile, MemberUpdate
from off_key_core.utils.mail import send_invitation_email
from off_key_tactic_middleware.services.accounts.members import MemberService

from ...providers import get_member_service
from ..access import current_member, require_permission
from ..errors import DomainErrorRoute

router = APIRouter(route_class=DomainErrorRoute)
me_router = APIRouter(route_class=DomainErrorRoute)
invitations_router = APIRouter(route_class=DomainErrorRoute)
manage_members = require_permission(Permission.manage_members)


@me_router.get("", response_model=MemberProfile)
async def get_me(user: User = Depends(current_member)):
    """The signed-in member: id, email, role, permissions and status."""
    return user


@router.get(
    "", response_model=list[MemberProfile], dependencies=[Depends(manage_members)]
)
async def list_members(service: MemberService = Depends(get_member_service)):
    """Every member and pending invitation. Needs `manage_members`."""
    return await service.list_members()


@invitations_router.post("")
async def create_invitation(
    invitation: MemberInvitation,
    actor: User = Depends(manage_members),
    service: MemberService = Depends(get_member_service),
):
    """Invite an email address with a role and send the invitation email.

    The link expires after 48 hours; inviting a pending address again sends a new one.
    Needs `manage_members`.
    """
    # The invitation is saved before the email leaves.
    result = await service.invite(invitation, actor)
    try:
        await send_invitation_email(result["email"], result["token"])
    except Exception:
        logger.error("event=member_invitation_delivery_failed")
        raise HTTPException(
            502, "Invitation saved, but email delivery failed. Check SMTP and resend."
        ) from None
    return {"message": "Invitation sent. The link expires in 48 hours."}


@router.patch("/{member_id}", response_model=MemberProfile)
async def update_member(
    member_id: int,
    change: MemberUpdate,
    actor: User = Depends(manage_members),
    service: MemberService = Depends(get_member_service),
):
    """Change a member's `role`, set `is_active`, or both. Needs `manage_members`.

    Fields left out keep their value. Refused with 409 when no active member
    could manage members afterwards.
    """
    return await service.update(member_id, change, actor)


@router.delete("/{member_id}", status_code=204, response_class=Response)
async def remove_member(
    member_id: int,
    actor: User = Depends(manage_members),
    service: MemberService = Depends(get_member_service),
):
    """Delete a disabled member and their favorites. Needs `manage_members`.

    Shared catalogue data, monitors and alarms are kept.
    """
    await service.remove(member_id, actor)
    return Response(status_code=204)
