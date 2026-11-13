from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

AgentName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
]
MAY_START = (
    "Whether the key may start monitoring services. Every key may read, design, "
    "test and propose."
)


class AgentProfile(BaseModel):
    """An agent that signs in with a key in place of a password."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    key_hint: str = Field(description="The last characters of the key.")
    may_start: bool = Field(description=MAY_START)
    created_by: str | None = Field(description="The member who created the key.")
    created_at: datetime


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: AgentName
    may_start: bool = Field(default=False, description=MAY_START)


class AgentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    may_start: bool = Field(description=MAY_START)


class AgentCreated(AgentProfile):
    key: str = Field(
        description=(
            "The key, sent as `Authorization: Bearer <key>`. It is shown this "
            "once and cannot be read again."
        )
    )
