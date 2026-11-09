"""Membership database bootstrap."""

from aberration_core.db.models import User
from aberration_core.schemas.members import MemberInvitation
from aberration_tactic_middleware.services.accounts.members import MemberService
from sqlalchemy import select

PASSWORD = "correct horse battery staple"


async def bootstrap(sessions):
    async with sessions() as session:
        service = MemberService(session)
        invitation = await service.invite(
            MemberInvitation(email="admin@example.com", role="admin")
        )
        await service.accept_invitation(invitation["token"], PASSWORD)
        return (
            await session.scalar(select(User).where(User.email == "admin@example.com"))
        ).id
