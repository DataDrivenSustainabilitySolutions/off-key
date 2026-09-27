from fastapi import APIRouter, Depends, Header, HTTPException
from off_key_core.config.logs import logger
from off_key_core.schemas.members import MemberInvitation, MemberProfile, MemberUpdate
from off_key_core.utils.mail import send_invitation_email

from ...facades.tactic import TacticError, tactic
from ..access import current_member, require_admin
from ..errors import raise_tactic_http_error

router = APIRouter()


async def member_request(method, path, authorization, body=None):
    try:
        return await tactic._make_request(
            method,
            f"/api/v1/members{path}",
            json_data=body,
            headers={"Authorization": authorization},
        )
    except TacticError as exc:
        raise_tactic_http_error(exc)


@router.get("/me", response_model=MemberProfile)
async def me(user: MemberProfile = Depends(current_member)):
    return user


@router.get(
    "", response_model=list[MemberProfile], dependencies=[Depends(require_admin)]
)
async def list_members(authorization: str = Header()):
    return await member_request("GET", "", authorization)


@router.post("/invitations", dependencies=[Depends(require_admin)])
async def invite(invitation: MemberInvitation, authorization: str = Header()):
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
    user_id: int, change: MemberUpdate, authorization: str = Header()
):
    return await member_request(
        "PUT",
        f"/{user_id}",
        authorization,
        change.model_dump(mode="json"),
    )
