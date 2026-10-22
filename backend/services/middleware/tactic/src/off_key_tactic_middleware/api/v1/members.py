from fastapi import APIRouter, Depends, Response
from off_key_core.db.base import get_db_async
from off_key_core.db.models import User
from off_key_core.schemas.members import (
    AcceptInvitation,
    MemberInvitation,
    MemberProfile,
    MemberUpdate,
    PasswordReset,
)
from off_key_core.schemas.sessions import RememberedSessionToken
from off_key_core.schemas.user import ForgotPasswordRequest
from sqlalchemy.ext.asyncio import AsyncSession

from ...services.members import MemberService
from ...services.remembered_sessions import RememberedSessionService
from ..collection_auth import current_member, require_admin
from ..errors import DomainErrorRoute

router = APIRouter(prefix="/members", tags=["members"], route_class=DomainErrorRoute)


def member_service(session: AsyncSession = Depends(get_db_async)) -> MemberService:
    return MemberService(session)


def remembered_session_service(
    session: AsyncSession = Depends(get_db_async),
) -> RememberedSessionService:
    return RememberedSessionService(session)


@router.post("/sessions")
async def create_remembered_session(
    user: User = Depends(current_member),
    service: RememberedSessionService = Depends(remembered_session_service),
):
    return await service.create(user)


@router.post("/sessions/refresh")
async def refresh_remembered_session(
    request: RememberedSessionToken,
    service: RememberedSessionService = Depends(remembered_session_service),
):
    return await service.refresh(request.token)


@router.post("/sessions/revoke")
async def revoke_remembered_session(
    request: RememberedSessionToken,
    service: RememberedSessionService = Depends(remembered_session_service),
):
    await service.revoke(request.token)
    return {"message": "Remembered session ended"}


@router.get("/me", response_model=MemberProfile)
async def me(user: User = Depends(current_member)):
    return user


@router.get(
    "", response_model=list[MemberProfile], dependencies=[Depends(require_admin)]
)
async def list_members(service: MemberService = Depends(member_service)):
    return await service.list_members()


@router.post("/invitations")
async def invite(
    invitation: MemberInvitation,
    actor: User = Depends(require_admin),
    service: MemberService = Depends(member_service),
):
    return await service.invite(invitation, actor)


@router.put("/{user_id}", response_model=MemberProfile)
async def update_member(
    user_id: int,
    change: MemberUpdate,
    actor: User = Depends(require_admin),
    service: MemberService = Depends(member_service),
):
    return await service.update(user_id, change, actor)


@router.delete("/{user_id}", status_code=204, response_class=Response)
async def remove_member(
    user_id: int,
    actor: User = Depends(require_admin),
    service: MemberService = Depends(member_service),
):
    await service.remove(user_id, actor)
    return Response(status_code=204)


@router.post("/accept-invitation")
async def accept_invitation(
    invitation: AcceptInvitation,
    service: MemberService = Depends(member_service),
):
    await service.accept_invitation(invitation.token, invitation.password)
    return {"message": "Account activated. You can now sign in."}


@router.post("/request-password-reset")
async def request_password_reset(
    request: ForgotPasswordRequest,
    service: MemberService = Depends(member_service),
):
    return await service.issue_reset_token(str(request.email))


@router.post("/reset-password")
async def reset_password(
    request: PasswordReset,
    service: MemberService = Depends(member_service),
):
    await service.reset_password(request.token, request.new_password)
    return {"message": "Password has been successfully reset"}
