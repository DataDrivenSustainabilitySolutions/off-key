"""
Database models for MQTT RADAR service.

Note: Anomalies are now written to the core 'anomalies' table (TimescaleDB hypertable)
managed by off_key_core. This module contains only auxiliary models for service
metrics and model checkpoints.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()

# Detector context keys, in precedence order, and the phase that scores live data.
INFERENCE_PHASES = {"static_conformal": "ready", "adaptive_stream": "operational"}


def strategy_context_key(context: dict[str, Any] | None) -> str | None:
    """Return the detector context key a result carries, if any."""
    context = context or {}
    return next(
        (key for key in INFERENCE_PHASES if isinstance(context.get(key), dict)), None
    )


def inference_key(context: dict[str, Any] | None) -> str | None:
    """Return the detector context key of an inference result, if it is one."""
    key = strategy_context_key(context)
    if key is not None and context[key].get("phase") == INFERENCE_PHASES[key]:
        return key
    return None


def is_inference(context: dict[str, Any] | None) -> bool:
    return inference_key(context) is not None


class ModelCheckpoint(Base):
    """Database model for storing model checkpoints and metadata"""

    __tablename__ = "radar_model_checkpoints"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Model info
    model_type = Column(String(50), nullable=False)
    model_version = Column(String(50), nullable=False)
    checkpoint_path = Column(String(500), nullable=False)

    # Statistics
    processed_count = Column(Integer, nullable=False, default=0)
    anomaly_count = Column(Integer, nullable=False, default=0)
    anomaly_rate = Column(Float, nullable=False, default=0.0)

    # Performance metrics
    avg_processing_time = Column(Float, nullable=True)
    memory_usage_mb = Column(Float, nullable=True)

    # Timestamp
    created_timestamp = Column(DateTime, nullable=False, default=func.now())

    # Configuration used
    config_snapshot = Column(JSON, nullable=True)

    def __repr__(self):
        return (
            f"<ModelCheckpoint(id={self.id},"
            f" model_type='{self.model_type}',"
            f" processed_count={self.processed_count})>"
        )


class ServiceMetrics(Base):
    """Database model for storing service performance metrics"""

    __tablename__ = "radar_service_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Metrics snapshot
    timestamp = Column(DateTime, nullable=False, default=func.now(), index=True)

    # Processing metrics
    total_messages_processed = Column(Integer, nullable=False, default=0)
    total_anomalies_detected = Column(Integer, nullable=False, default=0)
    anomaly_rate = Column(Float, nullable=False, default=0.0)

    # Performance metrics
    avg_processing_time_ms = Column(Float, nullable=True)
    throughput_per_second = Column(Float, nullable=True)
    memory_usage_mb = Column(Float, nullable=True)

    # Error tracking
    error_count = Column(Integer, nullable=False, default=0)
    error_rate = Column(Float, nullable=False, default=0.0)

    # Service health
    service_status = Column(String(20), nullable=False)  # healthy, degraded, failed
    active_alerts = Column(JSON, nullable=True)

    def __repr__(self):
        return (
            f"<ServiceMetrics(id={self.id},"
            f" timestamp={self.timestamp}, status='{self.service_status}')>"
        )


@dataclass
class AnomalyResult:
    """Data class for anomaly detection results"""

    anomaly_score: float
    is_anomaly: bool
    severity: str
    timestamp: datetime
    model_info: dict[str, Any]
    raw_data: dict[str, Any]
    processed_features: dict[str, Any] | None = None
    topic: str | None = None
    charger_id: str | None = None
    context: dict[str, Any] | None = None

    @property
    def should_persist(self) -> bool:
        """One eligibility rule shared by ingestion and persistence."""
        return self.is_anomaly or is_inference(self.context)


@dataclass
class MQTTMessage:
    """Data class for MQTT messages"""

    topic: str
    payload: bytes
    qos: int = 0
    retain: bool = False
    timestamp: datetime | None = None
    received_monotonic: float | None = None

    def get_json_payload(self) -> dict[str, Any]:
        """Parse payload as JSON"""
        try:
            return json.loads(self.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError(f"Invalid JSON payload: {error}") from error


@dataclass
class HealthStatus:
    """Data class for service health status"""

    status: str  # healthy, degraded, failed, unknown
    timestamp: datetime
    components: dict[str, dict[str, Any]]
    metrics: dict[str, Any]
    active_alerts: list[str]
    uptime_seconds: float
