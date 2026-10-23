"""
Pydantic schemas for TACTIC middleware service.

These schemas define the data transfer objects used for API requests and responses.
"""

from datetime import datetime

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


class TelemetryDataPoint(BaseModel):
    """Single telemetry data point."""

    timestamp: str
    value: float | None
    created: str


class TelemetryCursorResponse(BaseModel):
    """Composite ingestion cursor for telemetry pagination."""

    created: str
    timestamp: str


class TelemetryPaginationResponse(BaseModel):
    """Telemetry page metadata."""

    limit: int
    has_more: bool
    next_cursor: TelemetryCursorResponse | None


class TelemetryPaginatedResponse(BaseModel):
    """Paginated response for telemetry data."""

    data: list[TelemetryDataPoint]
    pagination: TelemetryPaginationResponse


# =============================================================================
# User Schemas
# =============================================================================


class UserLoginRequest(BaseModel):
    """Request schema for user login."""

    email: str
    password: str


# =============================================================================
# Favorite Schemas
# =============================================================================


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


class MonitoringEvidenceResponse(BaseModel):
    """Persisted strategy-aware monitoring evidence for a charted sensor."""

    service_id: str
    timestamp: datetime
    sequence_number: int
    charger_id: str
    sensor_set: list[str]
    input_timestamps: dict[str, datetime]
    strategy: str
    model_type: str | None = None
    p_value: float | None = None
    anomaly_score: float | None = None
    e_value: float | None = None
    e_value_is_infinite: bool
    log_e_value: float | None = None
    restarted_martingale: float | None = None
    restarted_martingale_is_infinite: bool
    log_restarted_martingale: float | None = None
    tracker_results: list[dict[str, object]] = Field(default_factory=list)
    threshold: float
    alarm: bool


class MonitoringChartEvidenceResponse(BaseModel):
    """Minimal persisted evidence used by telemetry chart overlays."""

    service_id: str
    timestamp: datetime
    sequence_number: int
    sensor_set: list[str]
    input_timestamps: dict[str, datetime]
    strategy: str
    model_type: str | None = None
    anomaly_score: float | None = None
    restarted_martingale: float | None = None
    tracker_results: list[dict[str, object]] = Field(default_factory=list)
    threshold: float
    alarm: bool
    created: datetime


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "AnomalyCreateRequest",
    "AnomalyResponse",
    "ChargerResponse",
    "FavoriteMutationRequest",
    "MonitoringChartEvidenceResponse",
    "MonitoringEvidenceResponse",
    "TelemetryCursorResponse",
    "TelemetryDataPoint",
    "TelemetryPaginatedResponse",
    "TelemetryPaginationResponse",
    "UserLoginRequest",
]
