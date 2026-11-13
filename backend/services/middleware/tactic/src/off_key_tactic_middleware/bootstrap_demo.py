"""Initialize an isolated demo once, after its administrator accepts the invitation.

Uses the normal catalogue/recording services. Later runs keep all admin edits,
including disabled readings. The viewer account has a dedicated restricted role.
"""

import asyncio
import json
import os

from off_key_core.auth.demo import DEMO_VIEWER_PERMISSIONS, DEMO_VIEWER_ROLE
from off_key_core.config.env import load_env
from off_key_core.db.base import get_async_engine, get_async_session_local
from off_key_core.db.models import MemberRole, User
from off_key_core.demo.catalogue import FeedSelection, catalogue
from off_key_core.demo.settings import DemoSettings
from off_key_core.schemas.members import validate_new_password
from off_key_core.schemas.system import SystemChange
from off_key_core.schemas.system_collection import SystemCollectionChange
from off_key_core.schemas.user import normalize_email
from sqlalchemy import select

from .domain import ConflictError
from .services.accounts.members import MemberService, _hash_password
from .services.catalogue.system import SystemService


async def ensure_viewer(session, email: str, password: str) -> None:
    email = normalize_email(email)
    validate_new_password(password)
    if len(password.encode()) < 32:
        raise ValueError("Use a dedicated random demo password of at least 32 bytes")
    members = MemberService(session)
    await members._lock_membership()
    if not await members._manager_count():
        raise ConflictError(
            "Accept the administrator invitation before initializing the demo"
        )
    role = await session.get(MemberRole, DEMO_VIEWER_ROLE)
    if role is not None and set(role.permissions) != DEMO_VIEWER_PERMISSIONS:
        raise ConflictError(
            "The demo viewer role was changed; review it before continuing"
        )
    if role is None:
        role = MemberRole(
            id=DEMO_VIEWER_ROLE,
            name="Public demo viewer",
            permissions=sorted(DEMO_VIEWER_PERMISSIONS),
        )
        session.add(role)
    user = await session.scalar(select(User).where(User.email == email))
    if user is not None and user.role != DEMO_VIEWER_ROLE:
        raise ConflictError("The viewer email belongs to another account")
    if user is None:
        user = User(
            email=email,
            hashed_password=_hash_password(password),
            is_active=True,
            is_verified=True,
            session_version=0,
        )
        user.member_role = role
        session.add(user)
    else:
        # Explicit operator initialization can rotate this server-only credential.
        # It never silently re-enables an account an administrator disabled.
        if not user.is_active or not user.is_verified:
            raise ConflictError(
                "The demo viewer was disabled; review it in member management"
            )
        import bcrypt

        if not bcrypt.checkpw(password.encode(), user.hashed_password.encode()):
            user.hashed_password = _hash_password(password)
            user.session_version += 1
    await session.commit()


async def seed_catalogue(session, selection: FeedSelection) -> dict:
    system = SystemService(session)
    if (await system.read()).storage_origin != "empty":
        return {"status": "kept"}
    document = catalogue(selection)
    saved = await system.save(
        SystemChange(expected_revision=0, document=document), actor="demo setup"
    )
    await system.apply_collection(
        SystemCollectionChange(
            expected_revision=saved.revision,
            expected_collection_revision=saved.runtime.collection_revision,
            stream_ids=[stream.id for stream in document.streams],
            policy=document.default_policy,
        ),
        actor="demo setup",
    )
    return {"status": "loaded", "readings": len(document.streams)}


async def main() -> None:
    load_env()
    settings = DemoSettings()
    if (
        not settings.DEMO_MODE
        or not settings.DEMO_VIEWER_EMAIL
        or not settings.DEMO_VIEWER_PASSWORD
    ):
        raise RuntimeError(
            "Demo initialization requires DEMO_MODE=true on an isolated deployment"
        )
    selection = FeedSelection.model_validate_json(
        os.environ.get("DEMO_FEEDS_JSON") or "{}"
    )
    try:
        async with get_async_session_local()() as session:
            await ensure_viewer(
                session,
                str(settings.DEMO_VIEWER_EMAIL),
                settings.DEMO_VIEWER_PASSWORD.get_secret_value(),
            )
            result = await seed_catalogue(session, selection)
            await session.commit()
        print(json.dumps(result))
    finally:
        await get_async_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
