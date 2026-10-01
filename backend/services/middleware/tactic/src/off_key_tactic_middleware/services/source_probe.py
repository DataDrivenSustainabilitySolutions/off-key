"""Briefly observe saved broker topics without changing collection resources."""

import time
from datetime import UTC, datetime
from uuid import uuid4

from off_key_core.schemas.collection import CatalogSource, SensorActivity, parse_value
from paho.mqtt.client import MQTT_ERR_SUCCESS, CallbackAPIVersion, Client

from ..config.collection import AmbiboxSettings
from ..domain import InfrastructureError

PROBE_SECONDS = 20
CONNECT_SECONDS = 5


def probe_source(
    source: CatalogSource, settings: AmbiboxSettings
) -> dict[str, dict[str, SensorActivity]]:
    topics = {
        sensor.upstream_topic: (str(charger.id), sensor)
        for charger in source.chargers
        for sensor in charger.sensors
    }
    if not topics:
        return {}
    state = {
        "topics": topics,
        "activity": {},
        "subscribed": False,
        "deadline": time.monotonic() + CONNECT_SECONDS,
    }
    client = Client(
        CallbackAPIVersion.VERSION2,
        client_id=f"offkey-probe-{uuid4().hex}",
        clean_session=True,
        userdata=state,
        reconnect_on_failure=False,
    )
    client.connect_timeout = CONNECT_SECONDS
    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    if settings.AMBIBOX_MQTT_USERNAME:
        client.username_pw_set(
            settings.AMBIBOX_MQTT_USERNAME,
            settings.AMBIBOX_MQTT_PASSWORD.get_secret_value(),
        )
    if settings.AMBIBOX_MQTT_TLS:
        client.tls_set()
    try:
        client.connect(settings.AMBIBOX_FORWARD_HOST, source.forward_port)
        while (remaining := state["deadline"] - time.monotonic()) > 0:
            if client.loop(timeout=min(1.0, remaining)) != MQTT_ERR_SUCCESS:
                raise InfrastructureError("The broker disconnected while listening.")
        if not state["subscribed"]:
            raise InfrastructureError(
                "The broker did not respond. Try listening again."
            )
        return state["activity"]
    except OSError as exc:
        raise InfrastructureError(
            "Could not connect to the broker. Try again."
        ) from exc
    finally:
        client.disconnect()


def on_connect(client, state, flags, reason, properties):
    if reason.is_failure:
        raise InfrastructureError("The broker rejected the listening connection.")
    result, _ = client.subscribe([(topic, 0) for topic in state["topics"]])
    if result != MQTT_ERR_SUCCESS:
        raise InfrastructureError("Could not subscribe to the broker's sensors.")


def on_subscribe(client, state, mid, reasons, properties):
    if any(reason.is_failure for reason in reasons):
        raise InfrastructureError("The broker denied access to its sensors.")
    state["subscribed"] = True
    state["deadline"] = time.monotonic() + PROBE_SECONDS


def on_message(client, state, message):
    binding = state["topics"].get(message.topic)
    if binding is None or len(message.payload) > 4096:
        return
    charger_id, sensor = binding
    try:
        parse_value(message.payload.decode("utf-8"), sensor.value_type)
    except (ValueError, OverflowError):
        return
    sensors = state["activity"].setdefault(charger_id, {})
    previous = sensors.get(sensor.key)
    if message.retain and previous and not previous.is_snapshot:
        return
    sensors[sensor.key] = SensorActivity(
        received_at=datetime.now(UTC), is_snapshot=message.retain
    )
