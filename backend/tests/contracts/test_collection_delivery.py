"""Real broker delivery distinguishes fresh observations from retained recovery."""

from unittest.mock import MagicMock

from off_key_core.utils.mqtt_lifecycle import close_client
from off_key_mqtt_proxy.client.facade import MQTTClient
from off_key_mqtt_proxy.collection_buffer import CollectionBuffer
from off_key_tactic_middleware.config.system_live import SystemLiveSettings
from off_key_tactic_middleware.services.catalogue import system_ingress
from paho.mqtt.client import Client
from paho.mqtt.enums import CallbackAPIVersion

from tests.support.collection import runtime_catalog
from tests.support.mqtt import mqtt_broker, proxy_config, wait_until


async def test_broker_preserves_latest_value_and_replays_it_only_as_a_snapshot(
    monkeypatch,
):
    monkeypatch.setattr(
        system_ingress, "get_system_live_settings", lambda: SystemLiveSettings()
    )
    async with mqtt_broker() as (_, port):
        publisher = Client(CallbackAPIVersion.VERSION2)
        publisher.connect_async("127.0.0.1", port)
        publisher.loop_start()
        collector = MQTTClient(proxy_config(port))
        ingress = system_ingress.SystemIngress()
        ingress._connect = MagicMock()
        ingress.output = publisher
        buffer = CollectionBuffer()
        collector.set_message_handler(buffer.receive)
        catalog = runtime_catalog("original")
        stream = catalog.streams()[0]
        try:
            await wait_until(publisher.is_connected)
            await ingress._configure(catalog)
            # Upstream publishes while the collector has not activated yet.
            ingress._receive(
                catalog.generation, "broker", stream.definition.topic, b"42", False
            )
            await ingress._forward_pending()
            buffer.configure(catalog, now=0)
            assert await collector.connect()
            assert await collector.subscribe(stream.ingress_topic)
            await wait_until(lambda: buffer.metrics()["sample_slots"] == 1)
            first = buffer.take(now=2)
            assert len(first) == 1 and first[0].snapshot and first[0].value == 42

            ingress._receive(
                catalog.generation, "broker", stream.definition.topic, b"43", False
            )
            await ingress._forward_pending()
            await wait_until(lambda: buffer.metrics()["original_queue"] == 1)
            fresh = buffer.take(now=2)
            assert len(fresh) == 1 and not fresh[0].snapshot and fresh[0].value == 43

            await collector.disconnect()
            buffer.configure(catalog, now=0)
            collector.set_message_handler(buffer.receive)
            assert await collector.connect()
            assert await collector.subscribe(stream.ingress_topic)
            try:
                await wait_until(lambda: buffer.metrics()["sample_slots"] == 1, 3)
            except TimeoutError as error:
                raise AssertionError(buffer.metrics()) from error
            recovered = buffer.take(now=2)
            assert (
                len(recovered) == 1
                and recovered[0].snapshot
                and recovered[0].value == 43
            )
            assert buffer.metrics()["original_queue"] == 0
        finally:
            await collector.disconnect()
            await close_client(publisher)
