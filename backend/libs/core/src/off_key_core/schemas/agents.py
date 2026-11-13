from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ..auth.agents import AgentStarts

AgentName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
]
STARTS = (
    "What the key may start without a member: `nothing`, services in `shadow`, "
    "which record the alarms they would raise and raise none, or `live` "
    "services as well. Every key may read, design, test and propose."
)


class AgentProfile(BaseModel):
    """An agent that signs in with a key in place of a password."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    key_hint: str = Field(description="The last characters of the key.")
    starts: AgentStarts = Field(description=STARTS)
    created_by: str | None = Field(description="The member who created the key.")
    created_at: datetime


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: AgentName
    starts: AgentStarts = Field(default=AgentStarts.nothing, description=STARTS)


class AgentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts: AgentStarts = Field(description=STARTS)


class AgentCreated(AgentProfile):
    key: str = Field(
        description=(
            "The key, sent as `Authorization: Bearer <key>`. It is shown this "
            "once and cannot be read again."
        )
    )
