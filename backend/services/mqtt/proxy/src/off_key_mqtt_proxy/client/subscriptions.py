"""Exact subscriptions, acknowledged by the broker before reporting success."""

import asyncio

import paho.mqtt.client as mqtt


class SubscriptionManager:
    def __init__(self, default_qos: int = 0):
        self.default_qos = default_qos
        self.client: mqtt.Client | None = None
        self.subscriptions: set[str] = set()
        self.pending_subscriptions: set[str] = set()
        self._acks: dict[tuple[str, int], asyncio.Future] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self.generation = 0

    def set_client(self, client: mqtt.Client) -> None:
        self.client = client
        self._loop = asyncio.get_running_loop()
        self.pending_subscriptions.update(self.subscriptions)
        self.subscriptions.clear()
        for future in self._acks.values():
            if not future.done():
                future.set_result(False)
        self._acks.clear()
        self.generation += 1
        client.on_subscribe = self._on_subscribe
        client.on_unsubscribe = self._on_unsubscribe

    async def _request(self, operation: str, topic: str, qos: int = 0) -> bool:
        if self.client is None or self._loop is None:
            return False
        result, mid = (
            self.client.subscribe(topic, qos)
            if operation == "subscribe"
            else self.client.unsubscribe(topic)
        )
        if result != mqtt.MQTT_ERR_SUCCESS:
            return False
        # Callbacks complete on this event loop, after the future is installed.
        future = self._loop.create_future()
        key = (operation, mid)
        self._acks[key] = future
        try:
            return await asyncio.wait_for(future, timeout=10)
        except TimeoutError:
            return False
        finally:
            self._acks.pop(key, None)

    async def subscribe(self, topic: str, qos: int | None = None) -> bool:
        self.pending_subscriptions.add(topic)
        if await self._request(
            "subscribe", topic, self.default_qos if qos is None else qos
        ):
            self.subscriptions.add(topic)
            self.pending_subscriptions.discard(topic)
            return True
        return False

    async def unsubscribe(self, topic: str) -> bool:
        # Do not restore unwanted topics when an acknowledgement is lost.
        self.pending_subscriptions.discard(topic)
        if await self._request("unsubscribe", topic):
            self.subscriptions.discard(topic)
            return True
        return False

    async def resubscribe_all(self) -> None:
        for topic in self.get_all_topics():
            await self.subscribe(topic)

    def get_subscriptions(self) -> set[str]:
        return self.subscriptions.copy()

    def get_pending_subscriptions(self) -> set[str]:
        return self.pending_subscriptions.copy()

    def get_all_topics(self) -> set[str]:
        return self.subscriptions | self.pending_subscriptions

    def get_subscription_count(self) -> int:
        return len(self.subscriptions)

    def clear_all(self) -> None:
        self.subscriptions.clear()
        self.pending_subscriptions.clear()

    def _ack(self, client, operation: str, mid: int, success: bool) -> None:
        def finish():
            future = self._acks.get((operation, mid))
            if client is self.client and future is not None and not future.done():
                future.set_result(success)

        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(finish)

    def _on_subscribe(self, client, userdata, mid, granted_qos):
        self._ack(
            client,
            "subscribe",
            mid,
            bool(granted_qos) and all(code < 128 for code in granted_qos),
        )

    def _on_unsubscribe(self, client, userdata, mid):
        self._ack(client, "unsubscribe", mid, True)
