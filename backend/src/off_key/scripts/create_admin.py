
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from off_key.db.base import get_db_async
from off_key.db.models import User
from off_key.core.config import settings
from off_key.utils.enum import RoleEnum
from off_key.services.auth import (
    get_password_hash,
)


async def create_admin():
    async for db in get_db_async():  
        email = settings.EMAIL_USERNAME
        password = settings.EMAIL_PASSWORD

        print(f"Checking if admin already exists...")

        result = await db.execute(select(User).where(User.email == email))
        existing_user = result.scalars().first()

        if existing_user:
            print("Admin already exists.")
            return

        hashed_pw = get_password_hash(password)

        admin_user = User(
            email=email,
            hashed_password=hashed_pw,
            is_verified=True,
            role=RoleEnum.admin.value,
        )

        db.add(admin_user)
        await db.commit()
        print(" Admin successfully created.")


if __name__ == "__main__":
    asyncio.run(create_admin())
