"""Simulate a saved generic catalogue with separate, real local MQTT brokers.

Generated files contain private catalogue information and belong in local state.
The saved catalogue itself is never changed. No broker publishes retained data.
"""

import argparse
import hashlib
import ipaddress
import json
import math
import os
import signal
import threading
import time
from collections import defaultdict
from pathlib import Path


def compose_fixture(document: dict, root: Path, catalogue: Path, image: str) -> dict:
    if not 1 <= len(document["connections"]) <= 128 or len(document["streams"]) > 4096:
        raise ValueError("Use 1–128 brokers and at most 4096 readings in this fixture.")
    hosts = [connection["host"] for connection in document["connections"]]
    if len(set(hosts)) != len(hosts):
        raise ValueError("This fixture requires a distinct hostname per broker.")
    services = {}
    for index, connection in enumerate(document["connections"]):
        try:
            ipaddress.ip_address(connection["host"])
        except ValueError:
            pass
        else:
            raise ValueError("Use DNS hostnames for isolated catalogue simulation.")
        if (
            connection["transport"] != "tcp"
            or connection["tls"]
            or connection["port"] != 1883
        ):
            raise ValueError(
                "The local catalogue fixture requires plain MQTT on port 1883."
            )
        services[f"catalogue-broker-{index:03}"] = {
            "image": "eclipse-mosquitto:2.0",
            "command": ["mosquitto", "-c", "/mosquitto/config/mosquitto.conf"],
            "volumes": [
                f"{root / 'dev/mosquitto/mosquitto.conf'}:/mosquitto/config/mosquitto.conf:ro"
            ],
            "networks": {"app-network": {"aliases": [connection["host"]]}},
            "mem_limit": "32m",
            "restart": "unless-stopped",
        }
    services["catalogue-publisher"] = {
        "image": image,
        "command": [
            "/app/bin/python",
            "/fixture.py",
            "publish",
            "--catalog",
            "/fixture.json",
        ],
        "volumes": [
            f"{root / 'dev/local/catalog_fixture.py'}:/fixture.py:ro",
            f"{catalogue}:/fixture.json:ro",
        ],
        "networks": ["app-network"],
        "depends_on": list(services),
        "mem_limit": "128m",
        "restart": "unless-stopped",
    }
    return {"services": services}


def generate(document: dict, root: Path, image: str) -> None:
    directory = root / "dev/local/state"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    catalogue = directory / "catalog-fixture.json"
    compose = directory / "catalog-fixture.compose.json"
    model = compose_fixture(document, root, catalogue, image)
    for path, data in [(catalogue, document), (compose, model)]:
        temporary = path.with_suffix(path.suffix + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w") as stream:
                stream.write(json.dumps(data, indent=2) + "\n")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def value_for(stream: dict, elapsed: float):
    phase = int(hashlib.sha256(stream["id"].encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    if stream["value_type"] == "boolean":
        return (int(elapsed / 20 + phase * 4) % 4) != 0
    if stream["value_type"] == "text":
        return "Operating" if int(elapsed / 25 + phase * 2) % 3 else "Idle"
    if stream["value_type"] == "identifier":
        return f"simulated-{int(elapsed / 30):04}"
    baseline = {
        "V": 230,
        "A": 12,
        "W": 3500,
        "kW": 3.5,
        "°C": 28,
        "%": 50,
        "Hz": 50,
    }.get(stream.get("unit"), 10 + phase * 60)
    return round(
        baseline
        + max(0.5, baseline * 0.04)
        * math.sin(elapsed / (8 + phase * 22) + phase * 6.28),
        3,
    )


def topic_payload(streams: list[dict], elapsed: float):
    pointers = [stream for stream in streams if stream.get("payload_pointer")]
    if not pointers:
        return value_for(streams[0], elapsed)
    result = {}
    for stream in pointers:
        keys = [
            key.replace("~1", "/").replace("~0", "~")
            for key in stream["payload_pointer"].split("/")[1:]
        ]
        parent = result
        for key in keys[:-1]:
            child = parent.setdefault(key, {})
            if not isinstance(child, dict):
                raise TypeError(
                    "The fixture cannot synthesize conflicting payload pointers."
                )
            parent = child
        parent[keys[-1]] = value_for(stream, elapsed)
    return result


def publish(document: dict) -> None:
    import paho.mqtt.client as mqtt

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    topics = defaultdict(lambda: defaultdict(list))
    for stream in document["streams"]:
        topics[stream["connection_id"]][stream["topic"]].append(stream)
    clients = []
    started = time.monotonic()
    try:
        for index, connection in enumerate(document["connections"]):
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"catalogue-simulation-{index}",
            )
            client.max_queued_messages_set(32)
            client.reconnect_delay_set(min_delay=1, max_delay=10)
            client.connect_async(f"catalogue-broker-{index:03}", 1883, keepalive=30)
            client.loop_start()
            clients.append([client, connection["id"], 1 + index % 5 * 0.25, 0.0])
        print(
            f"Simulated MQTT publisher ready: {len(clients)} local brokers; no retention.",
            flush=True,
        )
        while not stop.wait(0.1):
            elapsed = time.monotonic() - started
            for row in clients:
                client, connection_id, interval, next_tick = row
                if elapsed < next_tick or not client.is_connected():
                    continue
                row[3] = elapsed + interval
                for topic, streams in topics[connection_id].items():
                    client.publish(
                        topic,
                        json.dumps(topic_payload(streams, elapsed), allow_nan=False),
                        qos=0,
                        retain=False,
                    )
    finally:
        for client, *_ in clients:
            client.disconnect()
            client.loop_stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["publish", "generate"])
    parser.add_argument("--catalog", type=Path, required=True)
    args = parser.parse_args()
    document = json.loads(args.catalog.read_text())
    if args.command == "generate":
        from run import ENV_FILE, ROOT, read_environment

        values = read_environment(ENV_FILE)
        generate(document.get("document", document), ROOT, values["MQTT_PROXY_IMAGE"])
        print("Generated private catalogue simulation files in dev/local/state/.")
    else:
        publish(document)
