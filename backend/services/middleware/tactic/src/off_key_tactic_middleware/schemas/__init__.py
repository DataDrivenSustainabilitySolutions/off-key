"""
Pydantic schemas for TACTIC middleware service.

These schemas define the data transfer objects used for API requests and responses.
"""

from datetime import datetime
from typing import Any

from off_key_core.utils.enum import RoleEnum
from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Charger Schemas
# =============================================================================


class ChargerResponse(BaseModel):
    """Response schema for charger data."""

    model_config = ConfigDict(from_attributes=True)

    charger_id: str
    manufacturer_name: str | None = None
    charger_name: str | None = None
    firmware_version: str | None = None
    last_seen: str | None = None
    state: str | None = None
    online: bool
    created: datetime | None = None

    # MQTT status fields
    mqtt_connected: bool = False
    mqtt_last_message: datetime | None = None
    mqtt_subscription_status: dict | None = None
    mqtt_error_count: int = 0
    mqtt_last_error: str | None = None


# =============================================================================
# Telemetry Schemas
# =============================================================================


class TelemetryTypeResponse(BaseModel):
    """Response schema for telemetry types."""

    types: list[str]


class TelemetryDataPoint(BaseModel):
    """Single telemetry data point."""

    timestamp: str
    value: float | None


class TelemetryResponse(BaseModel):
    """Response schema for telemetry data."""

    model_config = ConfigDict(from_attributes=True)

    charger_id: str
    type: str
    timestamp: datetime
    value: float | None
    data_source: str
    created: datetime | None = None


class TelemetryPaginatedResponse(BaseModel):
    """Paginated response for telemetry data."""

    data: list[TelemetryDataPoint]
    pagination: dict[str, Any]


# =============================================================================
# User Schemas
# =============================================================================


class UserResponse(BaseModel):
    """Response schema for user data."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    is_verified: bool
    role: RoleEnum
    updated_at: datetime
    created_at: datetime


class UserCreateRequest(BaseModel):
    """Request schema for creating a user."""

    email: str = Field(..., max_length=255)
    hashed_password: str
    verification_token: str | None = None
    role: RoleEnum = RoleEnum.user


class UserLoginRequest(BaseModel):
    """Request schema for user login."""

    email: str
    password: str


class UserUpdateRequest(BaseModel):
    """Request schema for updating user."""

    hashed_password: str | None = None
    is_verified: bool | None = None
    verification_token: str | None = None


class UserPasswordUpdateRequest(BaseModel):
    """Request schema for password updates."""

    new_password_hash: str


# =============================================================================
# Favorite Schemas
# =============================================================================


class FavoriteResponse(BaseModel):
    """Response schema for favorites."""

    model_config = ConfigDict(from_attributes=True)

    favorite_id: int
    charger_id: str
    user_id: int


class FavoriteCreateRequest(BaseModel):
    """Request schema for creating a favorite."""

    user_id: int
    charger_id: str


class FavoriteMutationRequest(BaseModel):
    """Request schema for adding a favorite for a specific user."""

    charger_id: str


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


class AnomalyCreateRequest(BaseModel):
    """Request schema for creating an anomaly."""

    charger_id: str
    timestamp: datetime
    telemetry_type: str
    anomaly_type: str
    anomaly_value: float
    value_type: str | None = None
    sensor_set: list[str] | None = None


class MonitoringEvidenceResponse(BaseModel):
    """Persisted static conformal evidence for a charted sensor."""

    service_id: str
    timestamp: datetime
    sequence_number: int
    charger_id: str
    sensor_set: list[str]
    p_value: float
    e_value: float | None = None
    e_value_is_infinite: bool
    log_e_value: float | None = None
    restarted_martingale: float | None = None
    restarted_martingale_is_infinite: bool
    log_restarted_martingale: float | None = None
    threshold: float
    alarm: bool


# =============================================================================
# Generic Response Schemas
# =============================================================================


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str


class ErrorResponse(BaseModel):
    """Error response schema."""

    detail: str


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Charger
    "ChargerResponse",
    # Telemetry
    "TelemetryTypeResponse",
    "TelemetryDataPoint",
    "TelemetryResponse",
    "TelemetryPaginatedResponse",
    # User
    "UserResponse",
    "UserCreateRequest",
    "UserLoginRequest",
    "UserUpdateRequest",
    "UserPasswordUpdateRequest",
    # Favorite
    "FavoriteResponse",
    "FavoriteCreateRequest",
    "FavoriteMutationRequest",
    # Anomaly
    "AnomalyResponse",
    "AnomalyCreateRequest",
    # Generic
    "MessageResponse",
    "ErrorResponse",
]
