from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Form, Cookie
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ...core.config import settings
from ...db.base import get_db_sync
from ...db.crud import auth
from ...services import auth as auth_services
from ...schemas import users
from ...utils.mail import send_verification_email

router = APIRouter()


# Registration endpoint – creates user and sends verification email.
@router.post("/register", response_model=users.Token)
def register(user: users.UserCreate, db: Session = Depends(get_db_sync)):
    if auth.get_user_by_email(db, user.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )
    new_user = auth.create_user(db, user)

    # Generate a verification token (short expiry, e.g., 15 minutes)
    verification_token = auth_services.create_verification_token(
        new_user.email, expires_minutes=15
    )

    # Send verification email (could be run in background or in executor)
    import asyncio

    asyncio.create_task(send_verification_email(new_user.email, verification_token))

    # For now, return a token so the client may use it later if needed.
    access_token = auth_services.create_access_token(data={"sub": new_user.email})
    return {"access_token": access_token, "token_type": "bearer"}


# Email verification endpoint – user clicks the link received by email.
@router.get("/verify")
def verify_email(token: str, db: Session = Depends(get_db_sync)):
    email = auth_services.verify_verification_token(token)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token"
        )
    # Activate user account
    user = auth.update_user_active_status(db, email, True)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    # Redirect to a success page or return a message
    return JSONResponse(content={"message": "Email verified. You can now log in."})


# Login endpoint – only active users can log in.
@router.post("/login", response_model=users.Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db_sync)
):
    user = auth.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Email not verified"
        )
    access_token = auth_services.create_access_token(
        data={"sub": user.email},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": access_token, "token_type": "bearer"}
