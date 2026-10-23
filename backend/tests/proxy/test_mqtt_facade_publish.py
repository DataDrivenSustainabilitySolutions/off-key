"""The proxy's MQTT facade publishes only when connected and drains QoS>0 sends."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import paho.mqtt.client as mqtt
import pytest
from off_key_mqtt_proxy.client import facade
from off_key_mqtt_proxy.client.facade import MQTTClient

from tests.support.mqtt import proxy_config


class Info:
    """An MQTTMessageInfo whose delivery the test controls."""

    def __init__(self, rc=mqtt.MQTT_ERR_SUCCESS):
        self.rc = rc
        self.delivered = False

    def is_published(self):
        return self.delivered


class Paho:
    def __init__(self, *results):
        self.results = list(results)
        self.sent = []

    def publish(self, topic, payload, qos, retain):
        self.sent.append((topic, json.loads(payload), qos, retain))
        return self.results.pop(0)


def client(paho=None, connected=True):
    mqtt_client = MQTTClient(proxy_config())
    mqtt_client.connection_manager = SimpleNamespace(
        is_connected=connected, client=paho
    )
    return mqtt_client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("paho", "connected"),
    [(Paho(Info()), False), (None, True)],
    ids=["disconnected", "no-client"],
)
async def test_publish_refuses_without_a_connected_client(paho, connected):
    assert await client(paho, connected).publish("t", {"v": 1}) is False
    assert paho is None or paho.sent == []


@pytest.mark.asyncio
async def test_unsubscribe_refuses_while_disconnected():
    assert await client(connected=False).unsubscribe("t") is False


@pytest.mark.asyncio
async def test_failed_or_unencodable_publishes_report_false():
    paho = Paho(Info(rc=mqtt.MQTT_ERR_NO_CONN))
    mqtt_client = client(paho)

    assert await mqtt_client.publish("t", {"v": 1}) is False
    assert await mqtt_client.publish("t", {"v": object()}) is False
    assert mqtt_client._pending_publishes == []


@pytest.mark.asyncio
async def test_only_qos_publishes_are_drained_and_delivered_ones_pruned(monkeypatch):
    first, second, fire_and_forget = Info(), Info(), Info()
    paho = Paho(first, fire_and_forget, second)
    mqtt_client = client(paho)

    assert await mqtt_client.publish("a", {"v": 1}, qos=1) is True
    assert await mqtt_client.publish("b", {"v": 2}) is True
    first.delivered = True
    assert await mqtt_client.publish("c", {"v": 3}, qos=1, retain=True) is True
    assert mqtt_client._pending_publishes == [second]
    assert paho.sent[-1] == ("c", {"v": 3}, 1, True)

    def deliver(_):
        second.delivered = True

    sleep = AsyncMock(side_effect=deliver)
    monkeypatch.setattr(facade.asyncio, "sleep", sleep)
    await mqtt_client.drain_publishes()
    assert mqtt_client._pending_publishes == []
    sleep.assert_awaited_once()
