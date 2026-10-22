"""
Database models for MQTT RADAR service.

Results, messages and health snapshots exchanged between RADAR components.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

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
