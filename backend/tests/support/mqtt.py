"""Loopback MQTT brokers, misbehaving peers and polling helpers for socket tests."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from threading import Event

from amqtt.broker import Broker
from off_key_core.schemas.radar import AdaptiveStreamConfig
from off_key_mqtt_proxy.config.config import MQTTConfig

ANONYMOUS_ACCESS = {
    "amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}
}


async def start_mqtt_broker(*, plugins=None, port=0) -> tuple[Broker, int]:
    """Start an in-process broker on loopback and return it with its bound port."""
    broker = Broker(
        {
            "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
            "plugins": plugins or ANONYMOUS_ACCESS,
        }
    )
    await broker.start()
    return broker, broker._servers["default"].instance.sockets[0].getsockname()[1]


@asynccontextmanager
async def mqtt_broker(*, plugins=None, port=0):
    broker, port = await start_mqtt_broker(plugins=plugins, port=port)
    try:
        yield broker, port
    finally:
        await broker.shutdown()


@dataclass
class WithholdingServer:
    port: int
    accepted: asyncio.Event
    subscribed: asyncio.Event
    writers: set = field(default_factory=set)


async def _read_packet(reader):
    header = await reader.readexactly(1)
    size, multiplier = 0, 1
    while True:
        digit = (await reader.readexactly(1))[0]
        size += (digit & 127) * multiplier
        if not digit & 128:
            break
        multiplier *= 128
    return header, await reader.readexactly(size)


@asynccontextmanager
async def withholding_server(mode: str):
    """A TCP peer that never sends CONNACK (``connack``) or SUBACK (``suback``)."""
    assert mode in {"connack", "suback"}
    accepted, subscribed = asyncio.Event(), asyncio.Event()
    writers = set()

    async def handle(reader, writer):
        writers.add(writer)
        accepted.set()
        try:
            if mode == "suback":
                await _read_packet(reader)
                writer.write(b"\x20\x02\x00\x00")  # Real MQTT 3.1.1 CONNACK.
                await writer.drain()
                await _read_packet(reader)
                subscribed.set()
            await reader.read()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            writers.discard(writer)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    async with server:
        peer = WithholdingServer(
            server.sockets[0].getsockname()[1], accepted, subscribed, writers
        )
        try:
            yield peer
        finally:
            # Even a failed resource assertion must close these peers before
            # Server.__aexit__ waits for their transports to disappear.
            for writer in tuple(writers):
                writer.close()
                await writer.wait_closed()


@dataclass
class PausedSocketCreation:
    created: asyncio.Event
    release: Event


def paused_socket_creation(monkeypatch) -> PausedSocketCreation:
    """Hold every Paho TCP socket open but unreturned until ``release`` is set.

    This keeps a real connect in flight while the owner retires the client,
    exercising the connect/disconnect race deterministically.
    """
    from paho.mqtt.client import Client

    create_socket = Client._create_socket
    loop = asyncio.get_running_loop()
    paused = PausedSocketCreation(asyncio.Event(), Event())

    def pause(client):
        connection = create_socket(client)
        loop.call_soon_threadsafe(paused.created.set)
        if not paused.release.wait(5):
            connection.close()
            raise TimeoutError("Test did not release the connected socket")
        return connection

    monkeypatch.setattr(Client, "_create_socket", pause)
    return paused


async def wait_until(predicate, deadline_seconds=20):
    async with asyncio.timeout(deadline_seconds):
        # Broker, Paho thread and database state do not expose asyncio events.
        while not predicate():  # noqa: ASYNC110
            await asyncio.sleep(0.01)


def tiny_adaptive_monitoring() -> AdaptiveStreamConfig:
    """Adaptive detector that trains and calibrates within a handful of inputs."""
    return AdaptiveStreamConfig(
        model_type="aberrant_knn",
        model_params={"k": 1, "window_size": 8, "warm_up": 1},
        training_window_size=2,
        calibration_window_size=3,
    )


def observe(detector, value):
    """Score one single-sensor value with the alignment context RADAR records."""
    result = detector.process_data_point(
        {"x": float(value)}, topic="telemetry/entity/x", charger_id="entity"
    )
    result.context["alignment"] = {
        "aligned_vector": False,
        "input_timestamps": {"x": result.timestamp.isoformat()},
    }
    return result


def proxy_config(port: int = 1883, **overrides) -> MQTTConfig:
    """A plain-TCP, unauthenticated proxy configuration for a local broker."""
    return MQTTConfig(
        **{
            "broker_host": "127.0.0.1",
            "broker_port": port,
            "use_tls": False,
            "client_id_prefix": "contract",
            "use_auth": False,
            "mqtt_username": "",
            "mqtt_api_key": "",
            "enabled": True,
            "batch_size": 10,
            "batch_timeout": 0.5,
            "connection_timeout": 1.0,
            "max_message_queue_size": 100,
        }
        | overrides
    )
