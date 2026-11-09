from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr

__all__ = [
    "ForgotPasswordRequest",
    "NormalizedEmail",
    "UserLogin",
    "normalize_email",
]


def normalize_email(value: str) -> str:
    """Account emails are matched case-insensitively and stored lowercase."""
    return value.strip().lower()


NormalizedEmail = Annotated[EmailStr, AfterValidator(normalize_email)]


class UserLogin(BaseModel):
    email: NormalizedEmail
    password: str
    remember_me: bool = False


class ForgotPasswordRequest(BaseModel):
    email: NormalizedEmail
