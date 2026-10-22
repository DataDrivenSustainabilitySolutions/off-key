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
