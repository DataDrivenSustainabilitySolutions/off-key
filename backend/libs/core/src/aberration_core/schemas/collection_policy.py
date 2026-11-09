"""Explicit opt-in policies and bounded scalar values shared by ingestion."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CollectionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["off", "original", "sample"] = "off"
    interval_seconds: int = Field(default=10, ge=1, le=3600)

    @property
    def cadence(self) -> int | None:
        return self.interval_seconds if self.mode == "sample" else None
