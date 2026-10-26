"""Observed database storage and retention settings."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RetentionPolicyStatus(BaseModel):
    table: Literal["telemetry", "monitoring_evidence", "anomalies"]
    retention_days: float | None = Field(default=None, ge=0)
    scheduled: bool = False


class StorageStatus(BaseModel):
    database_size_bytes: int = Field(ge=0)
    retention_policies: list[RetentionPolicyStatus]
    # Ceiling on telemetry and monitoring evidence; None when no cap is configured.
    storage_cap_bytes: int | None = Field(default=None, ge=0)
    storage_cap_scheduled: bool = False
    capped_size_bytes: int = Field(default=0, ge=0)
    checked_at: datetime
