"""Paho teardown: disconnect, join the network thread, then close a late socket."""

import threading

import pytest
from off_key_core.utils.mqtt_lifecycle import close_client, close_client_blocking


class _Client:
    def __init__(self, late_socket):
        self.calls = []
        self.late_socket = late_socket
        self.join_thread = None

    def disconnect(self):
        self.calls.append("disconnect")

    def loop_stop(self):
        self.calls.append("loop_stop")
        self.join_thread = threading.current_thread()

    def socket(self):
        # A connect that finished after the first disconnect leaves a socket.
        return object() if self.late_socket and len(self.calls) == 2 else None


@pytest.mark.parametrize(
    ("late_socket", "calls"),
    [
        (False, ["disconnect", "loop_stop"]),
        (True, ["disconnect", "loop_stop", "disconnect"]),
    ],
)
async def test_async_teardown_joins_off_the_loop_and_closes_late_sockets(
    late_socket, calls
):
    client = _Client(late_socket)

    await close_client(client)

    assert client.calls == calls
    assert client.join_thread is not threading.current_thread()


@pytest.mark.parametrize(
    ("late_socket", "calls"),
    [
        (False, ["disconnect", "loop_stop"]),
        (True, ["disconnect", "loop_stop", "disconnect"]),
    ],
)
def test_blocking_teardown_closes_late_sockets(late_socket, calls):
    client = _Client(late_socket)

    close_client_blocking(client)

    assert client.calls == calls


def test_the_network_thread_is_joined_even_when_disconnect_raises():
    client = _Client(late_socket=False)
    client.disconnect = lambda: (_ for _ in ()).throw(OSError("closed"))

    with pytest.raises(OSError):
        close_client_blocking(client)

    assert client.calls == ["loop_stop"]
