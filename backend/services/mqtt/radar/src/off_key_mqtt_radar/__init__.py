"""
MQTT RADAR Service

Real-Time Anomaly Detection and Reporting system for MQTT telemetry data.
"""

__version__ = "0.1.0"
__title__ = "off-key-mqtt-radar"
__description__ = "MQTT Real-Time Anomaly Detector for Analysis and Reporting"
__author__ = "Oliver Hennhoefer, Fernando Saba"

from .service import RadarService, get_radar_service
from .config import radar_settings
from .models import AnomalyResult, MQTTMessage, HealthStatus

__all__ = [
    "RadarService",
    "get_radar_service",
    "radar_settings",
    "AnomalyResult",
    "MQTTMessage",
    "HealthStatus",
]
