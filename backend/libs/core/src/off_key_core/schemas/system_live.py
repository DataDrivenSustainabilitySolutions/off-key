"""Explicit temporary observation requests, separate from collection policies."""

from pydantic import BaseModel, ConfigDict, Field

from .system import EntityId


class SystemLiveStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    stream_ids: list[EntityId] | None = Field(default=None, max_length=4096)


class SystemLiveScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stream_ids: list[EntityId] | None = Field(default=None, max_length=4096)
