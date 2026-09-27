"""Observed database storage and retention settings."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RetentionPolicyStatus(BaseModel):
    table: Literal["telemetry", "monitoring_evidence"]
    retention_days: float | None = Field(default=None, ge=0)
    scheduled: bool = False


class StorageStatus(BaseModel):
    database_size_bytes: int = Field(ge=0)
    retention_policies: list[RetentionPolicyStatus]
    checked_at: datetime
