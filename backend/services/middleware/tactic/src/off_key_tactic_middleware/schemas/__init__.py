"""
Pydantic schemas for TACTIC middleware service.

These schemas define the data transfer objects used for API requests and responses.
"""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field
from off_key_core.utils.enum import RoleEnum

# =============================================================================
# Charger Schemas
# =============================================================================


class ChargerResponse(BaseModel):
    """Response schema for charger data."""

    charger_id: str
    manufacturer_name: Optional[str] = None
    charger_name: Optional[str] = None
    firmware_version: Optional[str] = None
    last_seen: Optional[str] = None
    state: Optional[str] = None
    online: bool
    created: Optional[datetime] = None

    # MQTT status fields
    mqtt_connected: bool = False
    mqtt_last_message: Optional[datetime] = None
    mqtt_subscription_status: Optional[dict] = None
    mqtt_error_count: int = 0
    mqtt_last_error: Optional[str] = None

    class Config:
        from_attributes = True


# =============================================================================
# Telemetry Schemas
# =============================================================================


class TelemetryTypeResponse(BaseModel):
    """Response schema for telemetry types."""

    types: list[str]


class TelemetryDataPoint(BaseModel):
    """Single telemetry data point."""

    timestamp: str
    value: Optional[float]


class TelemetryResponse(BaseModel):
    """Response schema for telemetry data."""

    charger_id: str
    type: str
    timestamp: datetime
    value: Optional[float]
    data_source: str
    created: Optional[datetime] = None

    class Config:
        from_attributes = True


class TelemetryPaginatedResponse(BaseModel):
    """Paginated response for telemetry data."""

    data: list[TelemetryDataPoint]
    pagination: dict[str, Any]


# =============================================================================
# User Schemas
# =============================================================================


class UserResponse(BaseModel):
    """Response schema for user data."""

    id: int
    email: str
    is_verified: bool
    role: RoleEnum
    updated_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class UserCreateRequest(BaseModel):
    """Request schema for creating a user."""

    email: str = Field(..., max_length=255)
    hashed_password: str
    verification_token: Optional[str] = None
    role: RoleEnum = RoleEnum.user


class UserLoginRequest(BaseModel):
    """Request schema for user login."""

    email: str
    password: str


class UserUpdateRequest(BaseModel):
    """Request schema for updating user."""

    hashed_password: Optional[str] = None
    is_verified: Optional[bool] = None
    verification_token: Optional[str] = None


class UserPasswordUpdateRequest(BaseModel):
    """Request schema for password updates."""

    new_password_hash: str


# =============================================================================
# Favorite Schemas
# =============================================================================


class FavoriteResponse(BaseModel):
    """Response schema for favorites."""

    favorite_id: int
    charger_id: str
    user_id: int

    class Config:
        from_attributes = True


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

    anomaly_id: str
    charger_id: str
    timestamp: datetime
    telemetry_type: str
    anomaly_type: str
    anomaly_value: float

    class Config:
        from_attributes = True


class AnomalyCreateRequest(BaseModel):
    """Request schema for creating an anomaly."""

    charger_id: str
    timestamp: datetime
    telemetry_type: str
    anomaly_type: str
    anomaly_value: float


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
