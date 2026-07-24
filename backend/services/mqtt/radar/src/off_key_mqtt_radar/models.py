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

from off_key_core.utils.mqtt_topics import TopicMetadataExtractor
from sqlalchemy import JSON, Column, DateTime, Float, Integer, String
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


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

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "anomaly_score": self.anomaly_score,
            "is_anomaly": self.is_anomaly,
            "severity": self.severity,
            "timestamp": (
                self.timestamp.isoformat()
                if isinstance(self.timestamp, datetime)
                else self.timestamp
            ),
            "model_info": self.model_info,
            "raw_data": self.raw_data,
            "processed_features": self.processed_features,
            "topic": self.topic,
            "charger_id": self.charger_id,
            "context": self.context,
        }


@dataclass
class MQTTMessage:
    """Data class for MQTT messages"""

    topic: str
    payload: bytes
    qos: int = 0
    retain: bool = False
    timestamp: datetime | None = None

    _topic_extractor = TopicMetadataExtractor()

    def get_json_payload(self) -> dict[str, Any]:
        """Parse payload as JSON"""
        try:
            return json.loads(self.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError(f"Invalid JSON payload: {error}") from error

    def extract_charger_id(self) -> str | None:
        """Extract charger ID from topic pattern"""
        metadata = self._topic_extractor.extract(topic=self.topic, payload=None)
        return metadata.charger_id if metadata else None


@dataclass
class HealthStatus:
    """Data class for service health status"""

    status: str  # healthy, degraded, failed, unknown
    timestamp: datetime
    components: dict[str, dict[str, Any]]
    metrics: dict[str, Any]
    active_alerts: list[str]
    uptime_seconds: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary"""
        return {
            "status": self.status,
            "timestamp": self.timestamp.isoformat(),
            "components": self.components,
            "metrics": self.metrics,
            "active_alerts": self.active_alerts,
            "uptime_seconds": self.uptime_seconds,
        }
