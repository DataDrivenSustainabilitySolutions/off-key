"""
MQTT RADAR Service

Real-Time Anomaly Detection and Reporting system for MQTT telemetry data.
"""

__version__ = "0.1.0"
__title__ = "off-key-mqtt-radar"
__description__ = "MQTT Real-Time Anomaly Detector for Analysis and Reporting"
__author__ = "Oliver Hennhoefer, Fernando Saba"

from .models import AnomalyResult, HealthStatus, MQTTMessage
from .service import RadarService, get_radar_service

__all__ = [
    "RadarService",
    "get_radar_service",
    "AnomalyResult",
    "MQTTMessage",
    "HealthStatus",
]
