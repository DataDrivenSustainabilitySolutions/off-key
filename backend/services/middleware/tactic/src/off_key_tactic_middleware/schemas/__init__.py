"""
Pydantic schemas for TACTIC middleware service.

These schemas define the data transfer objects used for API requests and responses.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

# =============================================================================
# User Schemas
# =============================================================================


class UserLoginRequest(BaseModel):
    """Request schema for user login."""

    email: str
    password: str


# =============================================================================
# Anomaly Schemas
# =============================================================================


class AnomalyResponse(BaseModel):
    """Response schema for anomaly data."""

    model_config = ConfigDict(from_attributes=True)

    anomaly_id: str
    charger_id: str
    timestamp: datetime
    telemetry_type: str
    anomaly_type: str
    anomaly_value: float
    value_type: str | None = None
    sensor_set: list[str] | None = None
    service_id: str | None = None


class AnomalyCreateRequest(BaseModel):
    """Request schema for creating an anomaly."""

    charger_id: str
    timestamp: datetime
    telemetry_type: str
    anomaly_type: str
    anomaly_value: float
    value_type: str | None = None
    sensor_set: list[str] | None = None


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "AnomalyCreateRequest",
    "AnomalyResponse",
    "UserLoginRequest",
]
