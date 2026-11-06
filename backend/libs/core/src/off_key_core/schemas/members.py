from datetime import datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)

from ..auth.permissions import MEMBER_ROLE, ROLE_ID_PATTERN, Permission
from .user import NormalizedEmail


def validate_new_password(value: str) -> str:
    if len(value) < 12 or len(value.encode("utf-8")) > 72:
        raise ValueError("Use at least 12 characters and at most 72 UTF-8 bytes")
    return value


NewPassword = Annotated[str, AfterValidator(validate_new_password)]
AccountToken = Annotated[str, Field(min_length=32, max_length=128)]
RoleId = Annotated[
    str,
    Field(
        pattern=ROLE_ID_PATTERN,
        description="A role's id, as `GET /v1/roles` lists it, such as `user`.",
    ),
]
RoleName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
]


class MemberProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str = Field(description="The id of the member's role.")
    permissions: list[Permission] = Field(
        description="What the member may change; every member can read."
    )
    is_active: bool
    is_verified: bool
    created_at: datetime


class MemberInvitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: NormalizedEmail
    role: RoleId = MEMBER_ROLE


class MemberUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: RoleId
    is_active: bool


class PermissionInfo(BaseModel):
    id: Permission
    description: str


class RoleProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    permissions: list[Permission]
    editable: bool = Field(
        description="False for `admin`, which always holds every permission."
    )
    built_in: bool = Field(description="`admin` and `user` cannot be deleted.")
    members: int = Field(description="Members and pending invitations holding it.")


class RoleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: RoleName
    permissions: list[Permission] = []


class RoleUpdate(BaseModel):
    """Change a role's name, its permissions, or both."""

    model_config = ConfigDict(extra="forbid")

    name: RoleName | None = None
    permissions: list[Permission] | None = None


class AcceptInvitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: AccountToken
    password: NewPassword


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: AccountToken
    new_password: NewPassword
