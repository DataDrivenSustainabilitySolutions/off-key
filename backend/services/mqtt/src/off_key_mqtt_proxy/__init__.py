"""
MQTT Proxy Service for Real-time Telemetry Processing

This package provides a complete MQTT proxy service that connects to the Pionix Cloud
MQTT broker and processes real-time telemetry data from EV chargers.

Components:
- API-Key authentication for Pionix Cloud access
- MQTT client with WebSocket/TLS support
- Message routing to multiple destinations
- Optimized database writer for telemetry data
- Charger discovery and subscription management
"""

from .proxy import MQTTProxyService
from .config import MQTTConfig
from .facade import MQTTClient
from .client.models import MQTTMessage

__all__ = ["MQTTProxyService", "MQTTConfig", "MQTTClient", "MQTTMessage"]
