"""Tear down a Paho client without leaking a socket that connected late.

Paho's reconnect sets CONNECTING before it opens its socket, so a connect in
flight during disconnect() can finish afterwards. Once the network thread has
joined it cannot open another socket, and a second disconnect() then closes
the late one synchronously. The helpers are duck-typed and import no Paho.
"""

import asyncio


def close_client_blocking(client) -> None:
    """For worker threads: disconnect, join the network thread, close late sockets."""
    try:
        client.disconnect()
    finally:
        client.loop_stop()
        if client.socket() is not None:
            client.disconnect()


async def close_client(client) -> None:
    """For the event loop: the same sequence with the join off the loop thread."""
    try:
        client.disconnect()
    finally:
        await asyncio.to_thread(client.loop_stop)
        if client.socket() is not None:
            client.disconnect()


_CONNACK_REFUSALS = {
    132: "Connection refused - incorrect protocol version",
    133: "Connection refused - invalid client identifier",
    136: "Connection refused - server unavailable",
    134: "Connection refused - bad username or password (check API key)",
    135: "Connection refused - not authorized (check permissions)",
}


def connack_refusal(reason_code) -> str:
    """Readable CONNACK refusal for a Callback API v2 reason code (or its int)."""
    code = getattr(reason_code, "value", reason_code)
    return _CONNACK_REFUSALS.get(code, f"Unknown error code {reason_code}")
