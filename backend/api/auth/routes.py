import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordRequestForm

from backend.services.database import Database
from backend.services.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    decode_token,
)
from schemas import UserCreate, UserLogin, Token
from models import User

router = APIRouter()
db = Database(os.getenv("DATABASE_URL"))


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(user: UserCreate):
    db_session = next(db.get_db())
    existing_user = db_session.query(User).filter(User.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = get_password_hash(user.password)
    new_user = User(email=user.email, hashed_password=hashed_password)
    db_session.add(new_user)
    db_session.commit()
    db_session.refresh(new_user)

    # Send welcome email
    from backend.tasks.email import send_welcome_email

    send_welcome_email(user.email)

    return {"message": "User created successfully"}


@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    db_session = next(db.get_db())
    user = db_session.query(User).filter(User.email == form_data.username).first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}
