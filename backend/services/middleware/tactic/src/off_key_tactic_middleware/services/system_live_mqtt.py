"""One reconnecting Paho network thread per explicitly approved connection."""

from collections.abc import Callable
from threading import RLock
from uuid import uuid4

from off_key_core.schemas.system import SystemConnection
from paho.mqtt.client import MQTT_ERR_SUCCESS, Client
from paho.mqtt.enums import CallbackAPIVersion
from socks import SOCKS5

from ..config.system_live import LiveCredential, LiveSocksProxy


class LiveMqttWorker:
    def __init__(
        self,
        connection: SystemConnection,
        topics: list[str],
        credential: LiveCredential | None,
        on_message: Callable,
        on_state: Callable,
        *,
        proxy: LiveSocksProxy | None = None,
        client_factory=Client,
    ):
        self.connection = connection
        self.topics = topics
        self.on_message = on_message
        self.on_state = on_state
        self.pending: set[int] = set()
        self.guard = RLock()
        self.connected = False
        self.stopping = False
        self.denied = False
        self.client = client_factory(
            CallbackAPIVersion.VERSION2,
            client_id=f"aberration-live-{uuid4().hex}",
            clean_session=True,
            transport="websockets" if connection.transport == "websocket" else "tcp",
            reconnect_on_failure=True,
        )
        self.client.connect_timeout = 5
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.max_queued_messages_set(32)
        self.client.on_connect = self._connected
        self.client.on_connect_fail = self._connect_failed
        self.client.on_subscribe = self._subscribed
        self.client.on_disconnect = self._disconnected
        self.client.on_message = self._message
        if proxy is not None:
            self.client.proxy_set(
                proxy_type=SOCKS5,
                proxy_addr=proxy.host,
                proxy_port=proxy.port,
                proxy_rdns=True,
                proxy_username=proxy.username or None,
                proxy_password=proxy.password.get_secret_value() or None,
            )
        if credential is not None:
            self.client.username_pw_set(
                credential.username, credential.password.get_secret_value()
            )
        if connection.tls:
            # Default trust store, server hostname checks, no insecure TLS option.
            self.client.tls_set()
        if connection.transport == "websocket":
            self.client.ws_set_options(path=connection.websocket_path or "/mqtt")

    def start(self) -> None:
        self.client.connect_async(
            self.connection.host, self.connection.port, keepalive=30
        )
        self.client.loop_start()

    def stop(self) -> None:
        with self.guard:
            self.stopping = True
            self.connected = False
        self.client.disconnect()
        self.client.loop_stop()

    def update_topics(self, topics: list[str]) -> bool:
        """Change an observation scope without replacing a healthy MQTT socket."""
        with self.guard:
            if self.stopping or self.denied:
                return False
            added = sorted(set(topics) - set(self.topics))
            removed = sorted(set(self.topics) - set(topics))
            self.topics = list(topics)
            if not self.connected:
                return True  # The connect callback subscribes to the latest scope.
            if added and not self._subscribe(self.client, added):
                return False
            if removed:
                result, _ = self.client.unsubscribe(removed)
                if result != MQTT_ERR_SUCCESS:
                    self.denied = True
                    self.on_state("error", "The broker could not update subscriptions.")
                    self.client.disconnect()
                    return False
            return True

    def _subscribe(self, client, topics: list[str]) -> bool:
        for offset in range(0, len(topics), 64):
            result, mid = client.subscribe(
                [(topic, 0) for topic in topics[offset : offset + 64]]
            )
            if result != MQTT_ERR_SUCCESS:
                self.denied = True
                self.on_state("error", "The broker could not accept subscriptions.")
                client.disconnect()
                return False
            self.pending.add(mid)
        return True

    def _connected(self, client, userdata, flags, reason, properties):
        with self.guard:
            if self.stopping:
                return
            if reason.is_failure:
                self.denied = True
                self.connected = False
                self.on_state(
                    "error", "The broker rejected the connection credentials."
                )
                return
            self.connected = True
            self.pending.clear()
            self.denied = False
            self.on_state("connecting", "Subscribing to the configured topics.")
            self._subscribe(client, self.topics)

    def _subscribed(self, client, userdata, mid, reasons, properties):
        with self.guard:
            if self.stopping or self.denied or not self.connected:
                return
            if any(reason.is_failure for reason in reasons):
                self.denied = True
                self.on_state("error", "The broker denied access to configured topics.")
                client.disconnect()
                return
            self.pending.discard(mid)
            if not self.pending:
                self.on_state("connected", None)

    def _connect_failed(self, client, userdata):
        if not self.stopping:
            self.on_state(
                "reconnecting", "Broker unavailable; retrying with bounded backoff."
            )

    def _disconnected(self, client, userdata, flags, reason, properties):
        with self.guard:
            self.connected = False
            self.pending.clear()
            if not self.stopping and not self.denied:
                self.on_state(
                    "reconnecting",
                    "Broker disconnected; retrying with bounded backoff.",
                )

    def _message(self, client, userdata, message):
        if not self.stopping:
            self.on_message(message.topic, message.payload, bool(message.retain))
