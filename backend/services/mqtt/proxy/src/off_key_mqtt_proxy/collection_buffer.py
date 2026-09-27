"""Bounded, thread-safe admission and latest-observation sampling."""

import json
import math
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass
from datetime import UTC, datetime

from off_key_core.schemas.collection import AmbiboxCatalog, CollectionStream

from .client.models import MQTTMessage


@dataclass(frozen=True)
class Observation:
    stream: CollectionStream
    value: float | bool | str
    received_at: datetime
    snapshot: bool

    def message(self) -> MQTTMessage:
        return MQTTMessage(
            topic=self.stream.accepted_topic,
            payload={"value": self.value, "timestamp": self.received_at.isoformat()},
            timestamp=self.received_at,
            qos=0,
            retain=False,
        )


def parse_value(value, kind: str) -> float | bool | str:
    if isinstance(value, str):
        if len(value.encode()) > 4096:
            raise ValueError("Oversized value")
        # Plain text/identifiers must preserve numeric-looking strings, including
        # leading zeros. Only decode them when the producer used a JSON string.
        if kind in {"number", "boolean"} or value.startswith('"'):
            value = json.loads(value)
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Expected a number")
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Non-finite value")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError("Expected a boolean")
    elif not isinstance(value, str) or len(value.encode()) > 4096 or "\x00" in value:
        raise ValueError("Expected bounded UTF-8 text without NUL")
    return value


def parse_observation(stream: CollectionStream, message: MQTTMessage) -> Observation:
    envelope = message.payload
    if not isinstance(envelope, dict):
        raise ValueError("Expected ingress envelope")
    value = parse_value(envelope["payload"], stream.sensor.value_type)
    millis = envelope["received_at"]
    if isinstance(millis, bool) or not isinstance(millis, (int, float)):
        raise ValueError("Expected broker observation time")
    received_at = datetime.fromtimestamp(millis / 1000, UTC)
    if received_at.timestamp() > time.time() + 300:
        raise ValueError("Future observation")
    retained = envelope["upstream_retained"]
    if not isinstance(retained, bool):
        raise ValueError("Expected retained flag")
    return Observation(stream, value, received_at, message.retain or retained)


class CollectionBuffer:
    def __init__(self, original_capacity: int = 10000):
        self._lock = threading.Lock()
        self._streams: dict[str, CollectionStream] = {}
        self._latest: dict[str, Observation] = {}
        self._deadlines: dict[str, float] = {}
        self._original: deque[Observation] = deque()
        self._capacity = original_capacity
        self._enabled = False
        self.counters: Counter = Counter()

    def pause(self) -> None:
        with self._lock:
            self._enabled = False
            self._latest.clear()
            self._original.clear()

    def configure(self, catalog: AmbiboxCatalog, *, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._streams = {
                s.ingress_topic: s for s in catalog.streams(selected_only=True)
            }
            self._latest.clear()
            self._original.clear()
            self._deadlines = {
                topic: now + (stream.policy.cadence or 1)
                for topic, stream in self._streams.items()
            }
            self._enabled = True

    def receive(self, message: MQTTMessage) -> None:
        # Paho network thread: no async task, log, or DB operation per input.
        with self._lock:
            self.counters["received"] += 1
            stream = self._streams.get(message.topic) if self._enabled else None
            if stream is None:
                self.counters["unselected"] += 1
                return
            try:
                observation = parse_observation(stream, message)
            except (KeyError, TypeError, ValueError, OverflowError, OSError):
                self.counters["invalid"] += 1
                return
            if observation.snapshot:
                self.counters["snapshots"] += 1
            if (
                stream.sensor.value_type == "number"
                and stream.policy.mode == "original"
                and not observation.snapshot
            ):
                if len(self._original) >= self._capacity:
                    self.counters["overload_dropped"] += 1
                    return
                self._original.append(observation)
            else:
                previous = self._latest.get(message.topic)
                if previous is not None:
                    if (
                        observation.snapshot and not previous.snapshot
                    ) or observation.received_at < previous.received_at:
                        self.counters["stale"] += 1
                        return
                    self.counters["coalesced"] += 1
                self._latest[message.topic] = observation

    def take(self, *, now: float | None = None, limit: int = 500) -> list[Observation]:
        now = time.monotonic() if now is None else now
        result = []
        with self._lock:
            if not self._enabled:
                return result
            for topic in list(self._latest):
                if len(result) >= limit:
                    break
                if now >= self._deadlines[topic]:
                    observation = self._latest.pop(topic)
                    result.append(observation)
                    self._deadlines[topic] = now + (
                        observation.stream.policy.cadence or 1
                    )
            while self._original and len(result) < limit:
                result.append(self._original.popleft())
        return result

    def count(self, event: str) -> None:
        with self._lock:
            self.counters[event] += 1

    def metrics(self) -> dict:
        with self._lock:
            return {
                **self.counters,
                "sample_slots": len(self._latest),
                "original_queue": len(self._original),
                "original_capacity": self._capacity,
            }
