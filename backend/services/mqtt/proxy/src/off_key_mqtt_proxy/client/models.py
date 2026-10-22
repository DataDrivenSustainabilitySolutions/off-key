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


class ConnectionState(Enum):
    """MQTT connection states"""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"


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
