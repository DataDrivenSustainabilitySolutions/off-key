"""
MQTT Proxy Service for Real-time Telemetry Processing

This package provides a complete MQTT proxy service that connects to a configured
MQTT source broker and processes real-time telemetry data from EV chargers.

Components:
- Optional username/API-key authentication
- MQTT client with TCP/WebSocket/TLS support
- Message routing to multiple destinations
- Optimized database writer for telemetry data
- Topic-pattern subscription management
"""

from .proxy import MQTTProxyService
from .config.config import MQTTConfig
from .client.facade import MQTTClient
from .client.models import MQTTMessage

__all__ = ["MQTTProxyService", "MQTTConfig", "MQTTClient", "MQTTMessage"]
