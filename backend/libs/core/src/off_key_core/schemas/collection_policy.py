"""Explicit opt-in policies and bounded scalar values shared by ingestion."""

import json
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CollectionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["off", "original", "sample"] = "off"
    interval_seconds: int = Field(default=10, ge=1, le=3600)

    @property
    def cadence(self) -> int | None:
        return self.interval_seconds if self.mode == "sample" else None


def parse_value(value, kind: str) -> float | bool | str:
    if isinstance(value, str):
        if len(value.encode()) > 4096:
            raise ValueError("Oversized value")
        # Plain text/identifiers must preserve numeric-looking strings, including
        # leading zeros. Only decode them when the producer used a JSON string.
        if kind in {"number", "boolean"} or value.startswith('"'):
            value = json.loads(value)
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Expected a number")
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Non-finite value")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError("Expected a boolean")
    elif not isinstance(value, str) or len(value.encode()) > 4096 or "\x00" in value:
        raise ValueError("Expected bounded UTF-8 text without NUL")
    return value
