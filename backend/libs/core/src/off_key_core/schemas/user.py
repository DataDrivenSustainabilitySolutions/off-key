from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr

__all__ = [
    "ForgotPasswordRequest",
    "NormalizedEmail",
    "ResetPasswordRequest",
    "UserCreate",
    "UserLogin",
    "UserVerification",
    "normalize_email",
]


def normalize_email(value: str) -> str:
    """Account emails are matched case-insensitively and stored lowercase."""
    return value.strip().lower()


NormalizedEmail = Annotated[EmailStr, AfterValidator(normalize_email)]


class UserCreate(BaseModel):
    email: NormalizedEmail
    password: str


class UserLogin(BaseModel):
    email: NormalizedEmail
    password: str
    remember_me: bool = False


class UserVerification(BaseModel):
    token: str


class ForgotPasswordRequest(BaseModel):
    email: NormalizedEmail


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
