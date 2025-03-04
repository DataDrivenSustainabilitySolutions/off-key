from sqlalchemy.orm import Session
from ...db import models
from ...schemas import users as schemas
from ...services.users import get_password_hash, verify_password


def get_user_by_email(db: Session, email: str):
    return db.query(models.Users).filter(models.User.email == email).first()


def create_user(db: Session, user: schemas.UserCreate):
    hashed_pw = get_password_hash(user.password)
    db_user = models.Users(email=user.email, hashed_password=hashed_pw)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def authenticate_user(db: Session, email: str, password: str):
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
