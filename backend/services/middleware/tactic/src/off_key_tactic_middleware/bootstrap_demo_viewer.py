"""Create or refresh the public demo's viewer member from the operator console."""

import asyncio
import json
import os

from off_key_core.config.env import load_env
from off_key_core.db.base import get_async_engine, get_async_session_local

from .services.accounts.members import MemberService


async def main() -> None:
    load_env()
    email = os.environ["DEMO_VIEWER_EMAIL"]
    password = os.environ["DEMO_VIEWER_PASSWORD"]
    try:
        async with get_async_session_local()() as session:
            result = await MemberService(session).ensure_demo_viewer(email, password)
        print(json.dumps(result))
    finally:
        await get_async_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
