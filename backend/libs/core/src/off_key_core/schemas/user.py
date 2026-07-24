from pydantic import BaseModel, EmailStr

__all__ = [
    "ForgotPasswordRequest",
    "ResetPasswordRequest",
    "UserCreate",
    "UserLogin",
    "UserVerification",
]


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: str | None = "user"


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
