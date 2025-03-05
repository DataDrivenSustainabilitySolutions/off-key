from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import models
from ...schemas import users as schemas
from ...services.auth import get_password_hash, verify_password


async def get_user_by_email(email: str, db: AsyncSession):
    result = await db.execute(select(models.Users).filter(models.Users.email == email))
    return result.scalars().first()


async def create_user(
    user: schemas.UserCreate, db: AsyncSession, is_superuser: bool = False
):
    hashed_pw = get_password_hash(user.password)
    db_user = models.Users(
        email=user.email,
        hashed_password=hashed_pw,
        is_active=True,
        is_superuser=is_superuser,
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user


async def update_user_active_status(email: str, active: bool, db: AsyncSession):
    user = await get_user_by_email(email, db)
    if user:
        user.is_active = active
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def authenticate_user(email: str, password: str, db: AsyncSession):
    user = await get_user_by_email(email, db)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user
