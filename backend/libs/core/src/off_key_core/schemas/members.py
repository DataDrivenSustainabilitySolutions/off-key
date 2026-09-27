from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

from ..utils.enum import RoleEnum


def validate_new_password(value: str) -> str:
    if len(value) < 12 or len(value.encode("utf-8")) > 72:
        raise ValueError("Use at least 12 characters and at most 72 UTF-8 bytes")
    return value


NewPassword = Annotated[str, AfterValidator(validate_new_password)]
AccountToken = Annotated[str, Field(min_length=32, max_length=128)]


class MemberProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: RoleEnum
    is_active: bool
    is_verified: bool
    created_at: datetime


class MemberInvitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    role: RoleEnum = RoleEnum.user


class MemberUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: RoleEnum
    is_active: bool


class AcceptInvitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: AccountToken
    password: NewPassword


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: AccountToken
    new_password: NewPassword
