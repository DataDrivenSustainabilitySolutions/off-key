"""
Shared MQTT Client Models and Data Structures

Contains the core data classes and enums used across all MQTT client components.
"""

import json
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any

import paho.mqtt.client as mqtt
from ....core.logs import logger


class ConnectionState(Enum):
    """MQTT connection states"""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


@dataclass
class MQTTMessage:
    """MQTT message data structure"""

    topic: str
    payload: Dict[str, Any]
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


class MQTTClientError(Exception):
    """MQTT client error"""

    pass
