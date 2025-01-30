# backend/api/auth/routes.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ...services.database import get_db_session
from ...services.security import get_password_hash, verify_password
from .schemas import UserCreate, UserLogin

router = APIRouter()

@router.post("/register")
async def register(user: UserCreate, db: Session = Depends(get_db_session)):
    # Registration logic
    pass

@router.post("/login")
async def login(user: UserLogin, db: Session = Depends(get_db_session)):
    # Login logic
    pass