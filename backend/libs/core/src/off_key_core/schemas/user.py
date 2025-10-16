from typing import Optional

from pydantic import BaseModel, EmailStr

__all__ = [
    "UserCreate",
    "UserLogin",
    "UserVerification",
    "ForgotPasswordRequest",
    "ResetPasswordRequest",
]


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: Optional[str] = "user"


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserVerification(BaseModel):
    token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
