"""Subscribe to public providers; publish selected readings to a private broker.

Run with ``python -m off_key_mqtt_proxy.demo.relay``. The same selection builds
the importable catalogue with ``--catalogue``. No credentials enter that file.
"""

import argparse
import json
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from off_key_core.demo.catalogue import (
    TRAFFIC_SENSORS,
    WEATHER_SENSORS,
    FeedSelection,
    catalogue,
)
from paho.mqtt.client import Client
from paho.mqtt.enums import CallbackAPIVersion

from .normalize import Normalizer

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Feed:
    id: str
    host: str
    topics: tuple[str, ...]
    port: int = 443
    path: str | None = "/mqtt"
    tls: bool = True


def feeds(selected: FeedSelection) -> tuple[Feed, ...]:
    return (
        # Digitraffic drops idle clients that subscribe to no status topic.
        Feed(
            "weather",
            "tie.digitraffic.fi",
            (
                *(
                    f"weather-v2/{selected.weather_station}/{sensor}"
                    for sensor in WEATHER_SENSORS.values()
                ),
                "weather-v2/status",
            ),
        ),
        Feed(
            "traffic",
            "tie.digitraffic.fi",
            (
                *(
                    f"tms-v2/{selected.traffic_station}/{sensor}"
                    for sensor in TRAFFIC_SENSORS.values()
                ),
                "tms-v2/status",
            ),
        ),
        Feed(
            "hamburg",
            "tld.iot.hamburg.de",
            tuple(
                f"v1.1/Datastreams({value})/Observations"
                for value in selected.hamburg_detectors
            ),
        ),
        Feed("solar", "mqtt.tdengine.com", ("inverters",), 1883, None, False),
    )


def subscriber(feed: Feed, receive) -> Client:
    client = Client(
        CallbackAPIVersion.VERSION2,
        client_id=f"aberration-demo-{uuid4().hex[:16]}",
        transport="websockets" if feed.path else "tcp",
    )
    client.reconnect_delay_set(5, 120)
    client.connect_timeout = 10
    if feed.path:
        client.ws_set_options(path=feed.path)
    if feed.tls:
        client.tls_set()

    def connected(client, _userdata, _flags, reason, _properties):
        if reason.is_failure:
            log.warning("source=%s connection_refused", feed.id)
            return
        client.subscribe([(topic, 0) for topic in feed.topics])
        log.info("source=%s subscribed", feed.id)

    def subscribed(_client, _userdata, _mid, reasons, _properties):
        if any(reason.is_failure for reason in reasons):
            log.warning("source=%s subscription_refused", feed.id)

    client.on_connect = connected
    client.on_subscribe = subscribed
    client.on_message = receive
    client.on_connect_fail = lambda *_: log.warning(
        "source=%s unavailable_retrying", feed.id
    )
    client.connect_async(feed.host, feed.port, keepalive=45)
    client.loop_start()
    return client


def run(selected: FeedSelection, output_host: str) -> None:
    output = Client(
        CallbackAPIVersion.VERSION2, client_id=f"demo-output-{uuid4().hex[:12]}"
    )
    output.reconnect_delay_set(1, 30)
    output.max_queued_messages_set(128)
    output.connect_async(output_host, 1883, keepalive=45)
    output.loop_start()
    clients = []
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    def receive_for(source: str):
        normalizer = Normalizer(selected)

        def receive(_client, _userdata, message):
            if not output.is_connected():
                return
            for destination, payload in normalizer.messages(
                source,
                message.topic,
                message.payload,
                received_at=time.time(),
                retained=message.retain,
            ):
                # Never replay buffered/retained values as fresh measurements.
                output.publish(destination, payload, qos=0, retain=False)

        return receive

    try:
        clients.extend(
            subscriber(feed, receive_for(feed.id)) for feed in feeds(selected)
        )
        stop.wait()
    finally:
        for client in [*clients, output]:
            client.disconnect()
            client.loop_stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalogue",
        action="store_true",
        help="Print an importable catalogue and exit",
    )
    parser.add_argument(
        "--selection",
        type=Path,
        help="JSON selections; otherwise read DEMO_FEEDS_JSON or use the examples",
    )
    args = parser.parse_args()
    selected = FeedSelection.model_validate_json(
        args.selection.read_text()
        if args.selection
        else os.environ.get("DEMO_FEEDS_JSON") or "{}"
    )
    host = os.environ.get("DEMO_RELAY_HOST", "demo-broker")
    if args.catalogue:
        print(
            json.dumps(
                catalogue(selected, host=host).model_dump(mode="json", by_alias=True),
                indent=2,
            )
        )
        return
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    run(selected, host)


if __name__ == "__main__":
    main()
