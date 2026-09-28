"""Issue an initial administrator invitation from the operator's trusted console."""

import argparse
import asyncio
import json
import os

from off_key_core.config.auth import get_auth_settings
from off_key_core.config.env import load_env
from off_key_core.db.base import get_async_engine, get_async_session_local
from off_key_core.schemas.members import MemberInvitation
from off_key_core.utils.enum import RoleEnum

from .services.members import MemberService


async def main(*, send_email: bool = False, resend: bool = False) -> None:
    load_env()
    origin = os.environ["FRONTEND_BASE_URL"].rstrip("/")
    try:
        async with get_async_session_local()() as session:
            service = MemberService(session)
            email = str(get_auth_settings().SUPERUSER_MAIL)
            if send_email:
                from off_key_core.utils.mail import (
                    get_mail_config,
                    send_invitation_email,
                )

                # Validate mail settings before creating a pending account.
                get_mail_config()
                invitation = await service.bootstrap_invitation(email, resend=resend)
                if invitation["status"] == "created":
                    try:
                        await send_invitation_email(email, invitation["token"])
                    except Exception:
                        raise RuntimeError(
                            "Administrator invitation saved, but email delivery "
                            "failed. Check SMTP credentials and sender verification, "
                            "then run bootstrap_admin --send-email --resend."
                        ) from None
                    invitation["status"] = "sent"
                # Deployment output must never contain a single-use account token.
                print(
                    json.dumps(
                        {
                            key: value
                            for key, value in invitation.items()
                            if key != "token"
                        }
                    )
                )
                return
            invitation = await service.invite(
                MemberInvitation(email=email, role=RoleEnum.admin)
            )
        # The operator must deliver this one-time link to the configured mailbox owner.
        print(f"{origin}/register#token={invitation['token']}")
    finally:
        await get_async_engine().dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--send-email",
        action="store_true",
        help="Email an invitation when setup is needed and print safe status JSON",
    )
    parser.add_argument(
        "--resend",
        action="store_true",
        help="Replace a pending invitation (requires --send-email)",
    )
    args = parser.parse_args()
    if args.resend and not args.send_email:
        parser.error("--resend requires --send-email")
    asyncio.run(main(send_email=args.send_email, resend=args.resend))
