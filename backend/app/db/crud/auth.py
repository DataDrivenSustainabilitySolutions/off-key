from sqlalchemy import select

from ..base import  AsyncSessionLocal
from ...db import models
from ...schemas import users as schemas
from ...services.auth import get_password_hash, verify_password


async def get_user_by_email(email: str):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(models.Users).filter(models.Users.email == email))
        return result.scalars().first()


async def create_user(user: schemas.UserCreate, is_superuser: bool = False):
    async with AsyncSessionLocal() as db:
        hashed_pw = get_password_hash(user.password)
        db_user = models.Users(
            email=user.email,
            hashed_password=hashed_pw,
            is_active=is_superuser,
            is_superuser=is_superuser,
        )
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user


async def update_user_active_status(email: str, active: bool):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_email(email)
        if user:
            user.is_active = active
            db.add(user)  # Add the user to the session explicitly
            await db.commit()
            await db.refresh(user)
        return user


async def authenticate_user(email: str, password: str):
    async with AsyncSessionLocal() as db:
        user = await get_user_by_email(db, email)
        if not user or not verify_password(password, user.hashed_password):
            return None
        return user
