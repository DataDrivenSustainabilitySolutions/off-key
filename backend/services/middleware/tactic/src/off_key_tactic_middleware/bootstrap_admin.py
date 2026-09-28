"""Issue an initial administrator invitation from the operator's trusted console."""

import asyncio
import os

from off_key_core.config.auth import get_auth_settings
from off_key_core.config.env import load_env
from off_key_core.db.base import get_async_engine, get_async_session_local
from off_key_core.schemas.members import MemberInvitation
from off_key_core.utils.enum import RoleEnum

from .services.members import MemberService


async def main() -> None:
    load_env()
    origin = os.environ["FRONTEND_BASE_URL"].rstrip("/")
    try:
        async with get_async_session_local()() as session:
            invitation = await MemberService(session).invite(
                MemberInvitation(
                    email=get_auth_settings().SUPERUSER_MAIL, role=RoleEnum.admin
                )
            )
        # The operator must deliver this one-time link to the configured mailbox owner.
        print(f"{origin}/register#token={invitation['token']}")
    finally:
        await get_async_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
