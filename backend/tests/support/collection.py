"""Collection catalogue and message builders."""

from datetime import UTC, datetime

from off_key_core.schemas.system import SystemDocument
from off_key_core.schemas.system_collection import (
    SystemCollectionDefinition,
    build_bindings,
)
from off_key_mqtt_proxy.client.models import MQTTMessage


def runtime_catalog(mode="sample", kind="number"):
    """One broker, device and reading, recorded with the given policy."""
    document = SystemDocument.model_validate(
        {
            "connections": [
                {"id": "broker", "label": "Broker", "host": "broker.example"}
            ],
            "devices": [{"id": "device", "label": "Device", "connection_id": "broker"}],
            "streams": [
                {
                    "id": "temperature",
                    "label": "Temperature",
                    "connection_id": "broker",
                    "device_id": "device",
                    "topic": "device/sensor/0/temperature",
                    "value_type": kind,
                    "policy": {"mode": mode, "interval_seconds": 10},
                }
            ],
        }
    )
    return SystemCollectionDefinition(
        document=document, bindings=build_bindings(document), generation="test"
    )


def message(configuration, value, *, retained=False, upstream_retained=False):
    now = datetime.now(UTC)
    return MQTTMessage(
        configuration.streams()[0].ingress_topic,
        {
            "payload": value
            if isinstance(value, str)
            else __import__("json").dumps(value),
            "received_at": int(now.timestamp() * 1000),
            "upstream_retained": upstream_retained,
        },
        now,
        0,
        retained,
    )
