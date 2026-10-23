"""Leased, shared MQTT observation; telemetry exists only in bounded memory."""

import asyncio
import hashlib
import time
from collections import OrderedDict, deque
from contextlib import suppress
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from off_key_core.schemas.system import SystemSnapshot
from off_key_core.utils.payload_decode import PayloadDecoder

from ...config.system_live import SystemLiveSettings
from .broker_access import ResolvedBroker, resolve_broker
from .system_live_mqtt import LiveMqttWorker


class LiveSessionError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


class _Rate:
    """Exact fresh-message counts in a bounded five-second observation window."""

    def __init__(self):
        self.buckets = deque(maxlen=6)

    def add(self, now: float) -> None:
        second = int(now)
        if self.buckets and self.buckets[-1][0] == second:
            self.buckets[-1][1] += 1
        else:
            self.buckets.append([second, 1])

    def value(self, now: float) -> float:
        return sum(count for second, count in self.buckets if second > now - 5) / 5


def _identity(snapshot: SystemSnapshot) -> tuple[int, str]:
    fingerprint = hashlib.sha256(
        snapshot.document.model_dump_json().encode()
    ).hexdigest()
    return snapshot.revision, fingerprint


class SystemLiveService:
    def __init__(
        self,
        settings: SystemLiveSettings,
        *,
        worker_factory=LiveMqttWorker,
        clock=time.monotonic,
        access_resolver=None,
    ):
        self.settings = settings
        self.worker_factory = worker_factory
        self.clock = clock
        self.access_resolver = access_resolver
        self.guard = RLock()
        self.operations = asyncio.Lock()
        self.leases: dict[str, tuple[int, float]] = {}
        self.lease_streams: dict[str, set[str]] = {}
        self.workers: list[LiveMqttWorker] = []
        self.connection_workers: dict[str, LiveMqttWorker] = {}
        self.connection_deadlines: dict[str, float] = {}
        self.connections: dict[str, dict] = {}
        self.streams: dict[str, dict] = {}
        self.bindings: dict[str, dict[str, list]] = {}
        self.samples: OrderedDict[tuple[str, int], dict] = OrderedDict()
        self.rates: dict[str, _Rate] = {}
        self.identity: tuple[int, str] | None = None
        self.revision = 0
        self.sequence = 0
        self.minimum_cursor = 0
        self.generation = 0
        self.supervisor: asyncio.Task | None = None

    def start_supervisor(self, read_snapshot) -> None:
        self.supervisor = asyncio.create_task(
            self._supervise(read_snapshot), name="generic-live-leases"
        )

    async def _supervise(self, read_snapshot) -> None:
        while True:
            await asyncio.sleep(2)
            if not self.leases:
                continue
            try:
                snapshot = await read_snapshot()
                await self.reconcile(snapshot)
            except Exception:
                # Database failure must not leave unowned broker workers alive.
                await self.stop()

    async def close(self) -> None:
        if self.supervisor is not None:
            self.supervisor.cancel()
            with suppress(asyncio.CancelledError):
                await self.supervisor
            self.supervisor = None
        await self.stop()

    async def reconcile(self, snapshot: SystemSnapshot) -> None:
        async with self.operations:
            await self._reconcile(snapshot)

    async def _reconcile(self, snapshot: SystemSnapshot) -> None:
        now = self.clock()
        self.leases = {
            lease: owner_expiry
            for lease, owner_expiry in self.leases.items()
            if owner_expiry[1] > now
        }
        self.lease_streams = {
            key: value
            for key, value in self.lease_streams.items()
            if key in self.leases
        }
        if self.identity is not None and (
            _identity(snapshot) != self.identity or not self.leases
        ):
            await self._stop_workers()
        elif self.identity is not None:
            await self._apply_scope(snapshot)
        self.revision = snapshot.revision
        await self._retire_failed_workers(now)

    async def _retire_failed_workers(self, now: float) -> None:
        retired = []
        timeout = self.settings.SYSTEM_LIVE_CONNECT_TIMEOUT_SECONDS
        with self.guard:
            for connection_id, worker in list(self.connection_workers.items()):
                state = self.connections[connection_id]
                deadline = self.connection_deadlines.get(connection_id)
                if deadline is not None and now >= deadline:
                    state.update(
                        state="error",
                        message=(
                            "Could not reach the broker within "
                            f"{timeout} seconds. "
                            "Check network or VPN access, then retry."
                        ),
                    )
                if state["state"] in {"error", "blocked", "stopped"}:
                    self.connection_workers.pop(connection_id)
                    self.connection_deadlines.pop(connection_id, None)
                    self.workers.remove(worker)
                    retired.append(worker)
        # Paho callbacks run on the worker thread. Join it from a separate
        # thread, after detaching it so late callbacks cannot revive it.
        if retired:
            await asyncio.gather(
                *(asyncio.to_thread(worker.stop) for worker in retired),
                return_exceptions=True,
            )

    async def acquire(
        self, snapshot: SystemSnapshot, owner: int, revision: int, stream_ids=None
    ) -> dict:
        async with self.operations:
            await self._reconcile(snapshot)
            if not self.settings.SYSTEM_LIVE_ENABLED:
                raise LiveSessionError(
                    503, "Live observation is disabled by the operator."
                )
            if revision != snapshot.revision:
                raise LiveSessionError(
                    409, "The saved system changed. Reload before listening."
                )
            if not snapshot.document.streams:
                raise LiveSessionError(
                    422, "Add a stream before starting live observation."
                )
            scope = self._validate_scope(snapshot, stream_ids)
            if len(self.leases) >= 64:
                raise LiveSessionError(429, "Too many simultaneous live views.")
            if self.identity is not None and not self.workers:
                # An explicit new lease retries a failed session, including
                # when other viewers still hold leases for its diagnostics.
                with self.guard:
                    self._clear_observation()
            lease = uuid4().hex
            self.leases[lease] = (
                owner,
                self.clock() + self.settings.SYSTEM_LIVE_LEASE_SECONDS,
            )
            self.lease_streams[lease] = scope
            if self.identity is None:
                self._initialize(snapshot, self._desired_scope())
            else:
                await self._apply_scope(snapshot)
            return self._lease_response(lease)

    async def renew(
        self, snapshot: SystemSnapshot, owner: int, lease: str, stream_ids=None
    ) -> dict:
        async with self.operations:
            await self._reconcile(snapshot)
            existing = self.leases.get(lease)
            if existing is None or existing[0] != owner:
                raise LiveSessionError(
                    404, "This live session ended. Start listening again."
                )
            if stream_ids is not None:
                self.lease_streams[lease] = self._validate_scope(
                    snapshot, stream_ids, replacing=lease
                )
                await self._apply_scope(snapshot)
            self.leases[lease] = (
                owner,
                self.clock() + self.settings.SYSTEM_LIVE_LEASE_SECONDS,
            )
            return self._lease_response(lease, self.sequence)

    async def release(self, owner: int, lease: str) -> None:
        async with self.operations:
            existing = self.leases.get(lease)
            if existing is not None and existing[0] != owner:
                raise LiveSessionError(
                    404, "This live session does not belong to this account."
                )
            self.leases.pop(lease, None)
            self.lease_streams.pop(lease, None)
            if not self.leases:
                await self._stop_workers()

    async def stop(self) -> None:
        async with self.operations:
            await self._stop_workers()

    async def _stop_workers(self) -> None:
        with self.guard:
            workers, self.workers = self.workers, []
            self.leases.clear()
            self.lease_streams.clear()
            self._clear_observation()
        if workers:
            await asyncio.gather(
                *(asyncio.to_thread(worker.stop) for worker in workers),
                return_exceptions=True,
            )

    def _clear_observation(self) -> None:
        self.generation += 1
        self.identity = None
        self.connection_workers.clear()
        self.connection_deadlines.clear()
        self.connections.clear()
        self.streams.clear()
        self.bindings.clear()
        self.rates.clear()
        self.samples.clear()
        self.sequence += 1
        self.minimum_cursor = self.sequence

    def _validate_scope(self, snapshot, stream_ids, *, replacing=None):
        known = {item.id for item in snapshot.document.streams}
        scope = set(stream_ids) if stream_ids is not None else known
        if not scope <= known:
            raise LiveSessionError(422, "Select existing readings for live viewing.")
        others = set().union(
            *(value for key, value in self.lease_streams.items() if key != replacing)
        )
        if len(scope | others) > self.settings.SYSTEM_LIVE_MAX_STREAMS:
            raise LiveSessionError(422, "The view exceeds the live stream limit.")
        return scope

    def _desired_scope(self):
        return (
            set().union(*self.lease_streams.values()) if self.lease_streams else set()
        )

    async def _apply_scope(self, snapshot):
        desired = self._desired_scope()
        if desired == set(self.streams):
            return
        bindings = {}
        for item in snapshot.document.streams:
            if item.id in desired:
                bindings.setdefault(item.connection_id, {}).setdefault(
                    item.topic, []
                ).append(item)
        topic_updates = [
            (key, worker, list(bindings[key]))
            for key, worker in self.connection_workers.items()
            if key in bindings and set(self.bindings.get(key, {})) != set(bindings[key])
        ]
        retired = self._retire_scope_connections(bindings)
        await asyncio.gather(
            *(asyncio.to_thread(item.stop) for item in retired), return_exceptions=True
        )
        with self.guard:
            self.bindings = bindings
            self.streams = {
                key: value for key, value in self.streams.items() if key in desired
            }
            self.samples = OrderedDict(
                (key, value) for key, value in self.samples.items() if key[0] in desired
            )
            self.sequence += 1
            self.minimum_cursor = self.sequence
            for stream in snapshot.document.streams:
                if stream.id in desired and stream.id not in self.streams:
                    self._add_stream(stream)
            for connection in snapshot.document.connections:
                if connection.id in bindings and connection.id not in self.connections:
                    self._initialize_connection(connection, self.generation)
            active = desired | set(bindings)
            self.rates = {
                key: value for key, value in self.rates.items() if key in active
            }
        for key, worker, topics in topic_updates:
            await self._update_scope_worker(snapshot, key, worker, topics)

    async def _update_scope_worker(self, snapshot, key, worker, topics):
        if self.connection_workers.get(key) is not worker:
            return
        try:
            updated = await asyncio.to_thread(worker.update_topics, topics)
        except Exception:
            updated = False
        if not updated:
            await asyncio.to_thread(worker.stop)
            with self.guard:
                self.connection_workers.pop(key, None)
                self.workers.remove(worker)
                self._initialize_connection(
                    next(
                        item for item in snapshot.document.connections if item.id == key
                    ),
                    self.generation,
                )

    def _retire_scope_connections(self, bindings):
        retired = []
        with self.guard:
            for key in list(self.connections):
                if set(self.bindings.get(key, {})) == set(bindings.get(key, {})):
                    continue
                worker = self.connection_workers.get(key)
                if (
                    key in bindings
                    and worker is not None
                    and callable(getattr(worker, "update_topics", None))
                    and self.connections[key]["state"]
                    in {"connected", "connecting", "reconnecting"}
                    and not getattr(worker, "denied", False)
                ):
                    continue
                worker = self.connection_workers.pop(key, None)
                self.connection_deadlines.pop(key, None)
                self.connections.pop(key, None)
                if worker is not None:
                    self.workers.remove(worker)
                    retired.append(worker)
        return retired

    def _add_stream(self, stream):
        self.streams[stream.id] = {
            "stream_id": stream.id,
            "value": None,
            "received_at": None,
            "fresh_received_at": None,
            "is_retained": False,
            "received_count": 0,
            "fresh_count": 0,
            "retained_count": 0,
            "decode_errors": 0,
            "rate_hz": 0.0,
            "sequence": self.sequence,
        }
        self.rates[stream.id] = _Rate()

    def _initialize(self, snapshot: SystemSnapshot, scope=None) -> None:
        with self.guard:
            self.identity = _identity(snapshot)
            self.revision = snapshot.revision
            self.generation += 1
            self.sequence += 1
            generation = self.generation
            for stream in snapshot.document.streams:
                if scope is not None and stream.id not in scope:
                    continue
                topics = self.bindings.setdefault(stream.connection_id, {})
                topics.setdefault(stream.topic, []).append(stream)
                self._add_stream(stream)
            for connection in snapshot.document.connections:
                if connection.id in self.bindings:
                    self._initialize_connection(connection, generation)

    def _initialize_connection(self, connection, generation: int) -> None:
        state = {
            "connection_id": connection.id,
            "state": "connecting",
            "message": None,
            "received_messages": 0,
            "fresh_count": 0,
            "retained_count": 0,
            "fresh_received_at": None,
        }
        self.connections[connection.id] = state
        self.rates[connection.id] = _Rate()
        topics = self.bindings.get(connection.id, {})
        if not topics:
            state.update(state="stopped", message="No streams use this connection.")
            return
        access = self.access_resolver(connection) if self.access_resolver else None
        resolved = self._resolve_connection(connection, access)
        if isinstance(resolved, str):
            state.update(state="blocked", message=resolved)
            return
        connection, credential, proxy = (
            resolved.connection,
            resolved.credential,
            resolved.proxy,
        )
        try:
            worker = self.worker_factory(
                connection,
                list(topics),
                credential,
                lambda topic, payload, retained: self._receive(
                    generation, connection.id, topic, payload, retained
                ),
                lambda status, message: self._connection_state(
                    generation, connection.id, status, message
                ),
                **({"proxy": proxy} if proxy is not None else {}),
            )
            self.workers.append(worker)
            self.connection_workers[connection.id] = worker
            self.connection_deadlines[connection.id] = (
                self.clock() + self.settings.SYSTEM_LIVE_CONNECT_TIMEOUT_SECONDS
            )
            worker.start()
        except Exception:
            # Public state must never include exception text, host credentials,
            # connection URLs, certificates, or MQTT payloads.
            state.update(
                state="error", message="Could not initialize the broker connection."
            )

    def _resolve_connection(self, connection, access) -> ResolvedBroker | str:
        """Checks run in a fixed order: capacity, access, then topic fan-out."""
        if len(self.workers) >= self.settings.SYSTEM_LIVE_MAX_CONNECTIONS:
            return "The connection exceeds the concurrent broker limit."
        resolved = resolve_broker(self.settings, connection, access)
        if resolved == "host_not_allowed":
            return "The broker is not in the operator's live host allowlist."
        if resolved == "credential_missing":
            return "The connection's private credential reference is unavailable."
        if any(
            len(streams) > 64
            for streams in self.bindings.get(connection.id, {}).values()
        ):
            return "A topic exceeds the limit of 64 bound streams."
        return resolved

    def _connection_state(self, generation, connection_id, status, message) -> None:
        with self.guard:
            if (
                generation != self.generation
                or connection_id not in self.connection_workers
                or self.connections[connection_id]["state"] == "error"
            ):
                return
            self.connections[connection_id].update(state=status, message=message)
            if status == "connected":
                self.connection_deadlines.pop(connection_id, None)
            elif status in {"connecting", "reconnecting"}:
                # Each outage has one deadline; individual retries and
                # subscription acknowledgements must not extend it.
                self.connection_deadlines.setdefault(
                    connection_id,
                    self.clock() + self.settings.SYSTEM_LIVE_CONNECT_TIMEOUT_SECONDS,
                )
            else:
                self.connection_deadlines.pop(connection_id, None)

    def _receive(self, generation, connection_id, topic, payload, retained) -> None:
        # Paho executes directly in its network thread. No event-loop callbacks
        # or unbounded queues are created, even for a high-frequency publisher.
        with self.guard:
            if (
                generation != self.generation
                or connection_id not in self.connection_workers
                or self.connections[connection_id]["state"] == "error"
            ):
                return
            streams = self.bindings.get(connection_id, {}).get(topic)
            if not streams:
                return
            now = self.clock()
            received_at = datetime.now(UTC).isoformat()
            connection = self.connections[connection_id]
            connection["received_messages"] += 1
            connection["retained_count" if retained else "fresh_count"] += 1
            if not retained:
                connection["fresh_received_at"] = received_at
                self.rates[connection_id].add(now)
            try:
                decoder = PayloadDecoder(payload)
            except (ValueError, UnicodeError):
                decoder = None
            for stream in streams:
                self._receive_stream(stream, decoder, retained, now, received_at)

    def _receive_stream(self, stream, decoder, retained, now, received_at) -> None:
        state = self.streams[stream.id]
        self.sequence += 1
        state["sequence"] = self.sequence
        state["received_count"] += 1
        state["retained_count" if retained else "fresh_count"] += 1
        if not retained:
            state["fresh_received_at"] = received_at
            self.rates[stream.id].add(now)
        try:
            if decoder is None:
                raise ValueError("Invalid payload")
            value = decoder.value(stream)
        except (ValueError, OverflowError, RecursionError):
            state["decode_errors"] += 1
            return
        state.update(value=value, received_at=received_at, is_retained=retained)
        # Last receipt per one-second bucket; full cumulative counts remain exact.
        key = (stream.id, int(now))
        self.samples[key] = {
            "sequence": self.sequence,
            "stream_id": stream.id,
            "received_at": received_at,
            "value": value,
            "is_retained": retained,
        }
        self.samples.move_to_end(key)
        while len(self.samples) > self.settings.SYSTEM_LIVE_MAX_SAMPLES:
            _, removed = self.samples.popitem(last=False)
            self.minimum_cursor = max(self.minimum_cursor, removed["sequence"])

    def _lease_response(self, lease: str, after_sequence: int = 0) -> dict:
        return {
            "lease_id": lease,
            "expires_in_seconds": self.settings.SYSTEM_LIVE_LEASE_SECONDS,
            "telemetry": self.snapshot(after_sequence),
        }

    def snapshot(self, after_sequence: int) -> dict:
        with self.guard:
            now = self.clock()
            cutoff = int(now) - self.settings.limits["history_seconds"]
            while self.samples and next(iter(self.samples))[1] < cutoff:
                _, removed = self.samples.popitem(last=False)
                self.minimum_cursor = max(self.minimum_cursor, removed["sequence"])
            for key, state in self.streams.items():
                rate = self.rates[key].value(now)
                if rate != state["rate_hz"]:
                    self.sequence += 1
                    state.update(rate_hz=rate, sequence=self.sequence)
            reset = (
                not after_sequence
                or not self.minimum_cursor <= after_sequence <= self.sequence
            )
            return {
                "mode": "live" if self.identity is not None else "configured_only",
                "data_source": self.settings.SYSTEM_LIVE_DATA_SOURCE,
                "revision": self.revision,
                "sequence": self.sequence,
                "reset": reset,
                "connections": [
                    {**state, "rate_hz": self.rates[key].value(now)}
                    for key, state in self.connections.items()
                ],
                "streams": [
                    state.copy()
                    for state in self.streams.values()
                    if reset or state["sequence"] > after_sequence
                ],
                "samples": [
                    sample.copy()
                    for sample in self.samples.values()
                    if reset or sample["sequence"] > after_sequence
                ],
                "limits": self.settings.limits,
            }
