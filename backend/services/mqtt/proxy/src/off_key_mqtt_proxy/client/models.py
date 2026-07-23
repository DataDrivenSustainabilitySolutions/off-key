"""
Shared MQTT Client Models and Data Structures

Contains the core data classes and enums used across all MQTT client components.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

import paho.mqtt.client as mqtt
from off_key_core.config.logs import logger
from off_key_core.utils.enum import HealthStatus


class ConnectionState(Enum):
    """MQTT connection states"""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


@dataclass
class ClientConnectionInfo:
    """MQTT client connection information"""

    state: str
    broker_host: str
    broker_port: int
    client_id: str | None
    connection_start_time: str | None
    reconnect_attempts: int
    subscriptions: list[str]
    pending_subscriptions: list[str]
    messages_sent: int


@dataclass
class ClientHealthStatus:
    """MQTT client health status"""

    status: HealthStatus
    state: str
    uptime_seconds: float
    messages_received: int
    messages_sent: int
    message_rate: float
    active_subscriptions: int
    reconnect_attempts: int
    queue_size: int
    last_message_time: str | None
    last_message_age_seconds: float | None


@dataclass
class MQTTMessage:
    """MQTT message data structure"""

    topic: str
    payload: dict[str, Any]
    timestamp: datetime
    qos: int
    retain: bool

    @classmethod
    def from_mqtt_message(cls, msg: mqtt.MQTTMessage) -> "MQTTMessage":
        """Create MQTTMessage from paho MQTT message"""
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Failed to decode message payload: {e}")
            payload = {"raw": msg.payload.decode(errors="ignore")}

        return cls(
            topic=msg.topic,
            payload=payload,
            timestamp=datetime.now(),
            qos=msg.qos,
            retain=msg.retain,
        )
