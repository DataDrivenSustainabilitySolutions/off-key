
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from off_key.db.base import get_db_async
from off_key.db.models import User
from off_key.core.config import settings
from off_key.utils.enum import RoleEnum
from off_key.services.auth import (
    create_reset_token,
    create_verification_token,
    get_password_hash,
    verify_password,
    create_jwt,
)


async def create_admin():
    async for db in get_db_async():  
        email = settings.ADMIN_EMAIL
        password = settings.ADMIN_PASSWORD

        print(f" Prüfe, ob Benutzer {email} existiert...")

        result = await db.execute(select(User).where(User.email == email))
        existing_user = result.scalars().first()

        if existing_user:
            print(" Admin-Benutzer existiert bereits.")
            return

        hashed_pw = get_password_hash(password)

        admin_user = User(
            email=email,
            hashed_password=hashed_pw,
            is_active=True,
            is_verified=True,
            role=RoleEnum.admin.value,
        )

        db.add(admin_user)
        await db.commit()
        print(" Admin-Benutzer erfolgreich erstellt.")


if __name__ == "__main__":
    asyncio.run(create_admin())
