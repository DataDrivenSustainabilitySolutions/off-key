"""Bounded, thread-safe admission and latest-observation sampling."""

import threading
import time
from collections import Counter, deque
from dataclasses import dataclass
from datetime import UTC, datetime

from off_key_core.schemas.collection_wire import decode_ingress_envelope
from off_key_core.schemas.system_collection import (
    SystemCollectionDefinition,
    SystemCollectionStream,
)
from off_key_core.utils.payload_decode import PayloadDecoder

from .client.models import MQTTMessage


@dataclass(frozen=True)
class Observation:
    stream: SystemCollectionStream
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


def parse_observation(
    stream: SystemCollectionStream, message: MQTTMessage
) -> Observation:
    payload, received_at, retained = decode_ingress_envelope(message.payload)
    value = PayloadDecoder(payload.encode("utf-8")).value(stream.definition)
    return Observation(stream, value, received_at, message.retain or retained)


class CollectionBuffer:
    def __init__(self, original_capacity: int = 10000):
        self._lock = threading.Lock()
        self._streams: dict[str, SystemCollectionStream] = {}
        self._latest: dict[str, Observation] = {}
        self._deadlines: dict[str, float] = {}
        self._original: deque[Observation] = deque()
        self._capacity = original_capacity
        self._enabled = False
        self.counters: Counter = Counter()
        self.last_received_at: datetime | None = None

    def pause(self) -> None:
        with self._lock:
            self._enabled = False
            self._latest.clear()
            self._original.clear()

    def configure(
        self, catalog: SystemCollectionDefinition, *, now: float | None = None
    ) -> None:
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
            self.last_received_at = datetime.now(UTC)
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
                stream.value_type == "number"
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
            self.counters["accepted"] += len(result)
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
