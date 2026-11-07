"""Long-lived selected subscriptions forward raw envelopes through internal EMQX.

Admission, sampling, persistence and accepted detector output remain exclusively
owned by mqtt-proxy. No view lease or browser connection controls this worker.
"""

import asyncio
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from off_key_core.config.logs import logger
from off_key_core.db.base import get_async_engine, get_async_session_local
from off_key_core.db.locks import SYSTEM_INGRESS_LOCK
from off_key_core.db.system import SystemCollectionConfiguration
from off_key_core.db.worker_ownership import WorkerOwnership
from off_key_core.schemas.collection_status import (
    INGRESS_APPLIED,
    INGRESS_CONNECTING,
    IngressWorkerState,
    is_prepared_or_applied,
)
from off_key_core.schemas.collection_wire import encode_ingress_envelope
from off_key_core.schemas.system_collection import SystemCollectionDefinition
from off_key_core.utils.mqtt_lifecycle import close_client
from off_key_core.utils.payload_decode import MAX_PAYLOAD_BYTES
from paho.mqtt.client import MQTT_ERR_SUCCESS, Client
from paho.mqtt.enums import CallbackAPIVersion
from sqlalchemy import select, text, update

from ...config.config import get_tactic_settings
from ...config.system_live import get_system_live_settings
from .arrival_cadence import ArrivalCadence
from .broker_access import resolve_broker
from .system_live_mqtt import LiveMqttWorker

# A deadline that has always passed: the broker's client gave up after a refusal.
REFUSED = float("-inf")
RETRY_HINT = "It is retried automatically; reconnect to try again now."
MAX_PENDING_MESSAGES = 512
MAX_PENDING_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class PendingMessage:
    generation: str
    connection_id: str
    attempt: object
    topic: str
    envelope: str
    size: int
    received_at: float
    retained: bool


class SystemIngress:
    def __init__(self, *, access_resolver=None, clock=time.monotonic):
        self.settings = get_system_live_settings()
        self.access_resolver = access_resolver
        self.clock = clock
        self.guard = RLock()
        self.workers = []
        self.states = {}
        # Per broker: what to (re)connect, its current worker and the attempt
        # whose callbacks may still change public state.
        self.sources = {}
        self.source_workers = {}
        self.attempts = {}
        # One deadline per outage; a broker past it, or whose client was refused,
        # is stopped and retried quietly (``quiet``) after a backoff that grows
        # with each failure.
        self.deadlines = {}
        self.retries = {}
        self.failures = {}
        self.quiet = set()
        self.bindings = {}
        self.readings = {}
        self.cadences = {}
        self._received_at_us = {}
        self.generation = None
        self.output = None
        self.task = None
        self.last_publish = None
        self.dropped = 0
        self.ownership: WorkerOwnership | None = None
        self.pending: deque[PendingMessage] = deque()
        self.pending_bytes = 0
        self.retained_topics: set[str] = set()
        self.effects = asyncio.Lock()

    async def start(self):
        if self.settings.SYSTEM_COLLECTION_ENABLED:
            self.task = asyncio.create_task(
                self._run(), name="system-collection-ingress"
            )

    async def stop(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        await self._stop_workers()
        if self.output is not None:
            await close_client(self.output)
            self.output = None

    def _make_output(self):
        endpoint = self.settings.collection_output_endpoint(
            get_tactic_settings().config.radar_defaults
        )
        client = Client(
            CallbackAPIVersion.VERSION2, client_id=f"aberration-ingress-{uuid4().hex}"
        )
        client.max_queued_messages_set(512)
        client.max_inflight_messages_set(32)
        client.reconnect_delay_set(1, 30)
        if endpoint.password is not None:
            client.username_pw_set(
                endpoint.username, endpoint.password.get_secret_value()
            )
        if endpoint.use_tls:
            client.tls_set(ca_certs=endpoint.ca_file)
        client.connect_async(endpoint.host, endpoint.port, 30)
        client.loop_start()
        return client

    async def _stop_workers(self):
        with self.guard:
            workers, self.workers = self.workers, []
            self.generation = None
            self.bindings = {}
            self.states = {}
            self.sources = {}
            self.source_workers = {}
            self.attempts = {}
            self.deadlines = {}
            self.retries = {}
            self.failures = {}
            self.quiet = set()
            self.readings = {}
            self.cadences = {}
            self.pending.clear()
            self.pending_bytes = 0
        await asyncio.gather(
            *(asyncio.to_thread(item.stop) for item in workers), return_exceptions=True
        )

    async def _configure(self, definition):
        await self._stop_workers()
        desired = {
            stream.ingress_topic for stream in definition.streams(selected_only=True)
        }
        obsolete = self.retained_topics - desired
        if obsolete:
            output = self.output
            if output is None:
                raise RuntimeError("Internal broker is disconnected")
            await self._acknowledge(
                [output.publish(topic, b"", qos=1, retain=True) for topic in obsolete]
            )
            self.retained_topics.difference_update(obsolete)
        with self.guard:
            self.generation = definition.generation
            for stream in definition.streams(selected_only=True):
                self.bindings.setdefault(stream.source_id, {}).setdefault(
                    stream.definition.topic, []
                ).append(stream)
            self._received_at_us = {
                key: timestamp
                for key, timestamp in self._received_at_us.items()
                if key[1] in self.bindings.get(key[0], {})
            }
            for connection in definition.document.connections:
                topics = self.bindings.get(connection.id)
                if not topics:
                    continue
                self._connect(connection, topics, definition.generation)

    def _connect(self, connection, topics, generation, *, quiet=False):
        """Start one broker client; a quiet retry keeps the reported failure
        until the broker is connected again."""
        access = self.access_resolver(connection) if self.access_resolver else None
        self.sources[connection.id] = (connection, topics)
        if quiet and connection.id in self.states:
            self.quiet.add(connection.id)
            state = self.states[connection.id]
        else:
            state = {"state": "connecting", "message": None}
            self.states[connection.id] = state
        resolved = resolve_broker(self.settings, connection, access)
        if resolved == "host_not_allowed":
            state.update(
                state="blocked",
                message="Broker access is not configured by the operator.",
            )
            return
        if resolved == "credential_missing":
            state.update(
                state="blocked",
                message="Broker credentials are not configured by the operator.",
            )
            return
        connection = resolved.connection
        attempt = object()
        try:
            worker = LiveMqttWorker(
                connection,
                list(topics),
                resolved.credential,
                lambda topic, payload, retained: self._receive(
                    generation, connection.id, topic, payload, retained, attempt
                ),
                lambda phase, message: self._state(
                    generation, connection.id, phase, message, attempt
                ),
                proxy=resolved.proxy,
            )
            self.workers.append(worker)
            self.source_workers[connection.id] = worker
            self.attempts[connection.id] = attempt
            self.deadlines[connection.id] = (
                self.clock() + self.settings.SYSTEM_COLLECTION_CONNECT_TIMEOUT_SECONDS
            )
            worker.start()
        except Exception:
            self.quiet.discard(connection.id)
            self.deadlines.pop(connection.id, None)
            state.update(
                state="error", message="Broker connection could not be initialized."
            )

    def _state(self, generation, connection_id, phase, message, attempt=None):
        with self.guard:
            # Late callbacks of a stopped or replaced client must not revive it.
            if (
                generation != self.generation
                or self.attempts.get(connection_id) is not attempt
            ):
                return
            if phase == "connected":
                self.deadlines.pop(connection_id, None)
                self.failures.pop(connection_id, None)
                self.quiet.discard(connection_id)
            elif phase in {"connecting", "reconnecting"}:
                # Individual retries and acknowledgements never extend an outage.
                self.deadlines.setdefault(
                    connection_id,
                    self.clock()
                    + self.settings.SYSTEM_COLLECTION_CONNECT_TIMEOUT_SECONDS,
                )
                if connection_id in self.quiet:
                    return
            else:
                # The client gave up for good: the broker refused the login or the
                # topics, and Paho does not reconnect after that. A broker that is
                # restarting refuses clients too, so retire this client at the next
                # supervision and retry it after the outage backoff, not never.
                self.deadlines[connection_id] = REFUSED
                self.quiet.discard(connection_id)
            self.states[connection_id].update(state=phase, message=message)

    def _detach(self, connection_id):
        """Forget a broker's client and timers; the caller stops the client."""
        worker = self.source_workers.pop(connection_id, None)
        self.attempts.pop(connection_id, None)
        self.deadlines.pop(connection_id, None)
        self.quiet.discard(connection_id)
        if worker is not None:
            self.workers.remove(worker)
        return worker

    async def _supervise(self):
        """Give up on brokers past their outage deadline; start due retries."""
        now = self.clock()
        timeout = self.settings.SYSTEM_COLLECTION_CONNECT_TIMEOUT_SECONDS
        retired = []
        with self.guard:
            for connection_id, deadline in list(self.deadlines.items()):
                if now < deadline:
                    continue
                refused = deadline == REFUSED
                worker = self._detach(connection_id)
                if worker is not None:
                    retired.append(worker)
                failures = self.failures.get(connection_id, 0) + 1
                self.failures[connection_id] = failures
                self.retries[connection_id] = now + min(
                    self.settings.SYSTEM_COLLECTION_RETRY_SECONDS
                    * 2 ** min(failures - 1, 16),
                    self.settings.SYSTEM_COLLECTION_RETRY_MAX_SECONDS,
                )
                state = self.states[connection_id]
                if refused:
                    message = (
                        f"{state['message'] or 'The broker refused the connection.'}"
                        f" {RETRY_HINT}"
                    )
                else:
                    message = (
                        f"Could not reach the broker within {timeout} seconds, "
                        f"so recording from it is paused. {RETRY_HINT}"
                    )
                state.update(state="error", message=message)
            for connection_id, due in list(self.retries.items()):
                if now >= due and connection_id in self.sources:
                    del self.retries[connection_id]
                    connection, topics = self.sources[connection_id]
                    self._connect(connection, topics, self.generation, quiet=True)
        await asyncio.gather(
            *(asyncio.to_thread(item.stop) for item in retired), return_exceptions=True
        )

    async def reconnect(self, connection_id) -> bool:
        """Replace a recorded broker's client now, resetting its backoff.

        Returns False when this process is not recording from that broker.
        """
        with self.guard:
            source = self.sources.get(connection_id)
            if source is None or self.generation is None:
                return False
            worker = self._detach(connection_id)
            self.retries.pop(connection_id, None)
            self.failures.pop(connection_id, None)
            self._connect(*source, self.generation)
        if worker is not None:
            await asyncio.to_thread(worker.stop)
        return True

    def _receive(
        self, generation, connection_id, topic, payload, retained, attempt=None
    ):
        with self.guard:
            if (
                generation != self.generation
                or self.attempts.get(connection_id) is not attempt
                or self.output is None
                or not self.output.is_connected()
            ):
                return
            if len(payload) > MAX_PAYLOAD_BYTES:
                self.dropped += 1
                return
            streams = self.bindings.get(connection_id, {}).get(topic, [])
            if not streams:
                return
            try:
                decoded = payload.decode("utf-8")
                key = (connection_id, topic)
                # PostgreSQL stores microseconds. Preserve separate arrivals even
                # when a network-thread burst shares one clock tick; all fields
                # from the same upstream message keep the same observation time.
                received_at_us = max(
                    time.time_ns() // 1000, self._received_at_us.get(key, 0) + 1
                )
                self._received_at_us[key] = received_at_us
                envelope = encode_ingress_envelope(
                    decoded, received_at_us / 1000, retained
                )
            except UnicodeError:
                self.dropped += 1
                return
            size = len(envelope.encode("utf-8"))
            if (
                len(self.pending) >= MAX_PENDING_MESSAGES
                or self.pending_bytes + size > MAX_PENDING_BYTES
            ):
                self.dropped += 1
                return
            self.pending.append(
                PendingMessage(
                    generation,
                    connection_id,
                    attempt,
                    topic,
                    envelope,
                    size,
                    received_at_us / 1_000_000,
                    retained,
                )
            )
            self.pending_bytes += size

    async def _acknowledge(self, publications):
        try:
            if any(info.rc != MQTT_ERR_SUCCESS for info in publications):
                raise RuntimeError("Internal broker refused a publication")
            async with asyncio.timeout(10):
                # Paho exposes a synchronous completion flag, not an async event.
                while not all(info.is_published() for info in publications):  # noqa: ASYNC110
                    await asyncio.sleep(0.01)
        except BaseException:
            # No queued publication may outlive its ownership fence.
            if self.output is not None:
                await close_client(self.output)
                self.output = None
            raise

    async def _publish_pending(self):
        output = self.output
        if output is None:
            return
        publications = []
        accepted = []
        for _ in range(32):
            with self.guard:
                if not self.pending:
                    break
                item = self.pending.popleft()
                self.pending_bytes -= item.size
                if (
                    item.generation != self.generation
                    or self.attempts.get(item.connection_id) is not item.attempt
                ):
                    continue
                streams = list(
                    self.bindings.get(item.connection_id, {}).get(item.topic, [])
                )
            for stream in streams:
                result = output.publish(
                    stream.ingress_topic, item.envelope, qos=1, retain=True
                )
                # Paho may queue a QoS publication even when returning NO_CONN.
                # An error therefore needs the same fenced transport teardown.
                publications.append(result)
                if result.rc == MQTT_ERR_SUCCESS:
                    accepted.append((item, stream))
                    self.retained_topics.add(stream.ingress_topic)
                else:
                    self.dropped += 1
        await self._acknowledge(publications)
        with self.guard:
            for item, stream in accepted:
                self.last_publish = datetime.now(UTC).isoformat()
                if (
                    item.retained
                    or item.generation != self.generation
                    or self.attempts.get(item.connection_id) is not item.attempt
                ):
                    continue
                cadence = self.cadences.get(stream.definition.id)
                if cadence is None:
                    cadence = ArrivalCadence()
                    self.cadences[stream.definition.id] = cadence
                cadence.add(item.received_at)
                self.readings[stream.definition.id] = {
                    "fresh_received_at": datetime.fromtimestamp(
                        item.received_at, UTC
                    ).isoformat(),
                    "typical_interval_seconds": cadence.typical_seconds,
                }

    async def _forward_pending(self):
        async with self.effects:
            if (
                not self.pending
                or self.output is None
                or not self.output.is_connected()
            ):
                return
            if self.ownership is None:
                await self._publish_pending()
                return
            async with get_async_session_local()() as session:
                await self.ownership.fence(session)
                try:
                    await self._publish_pending()
                    await session.commit()
                except BaseException:
                    if self.output is not None:
                        await close_client(self.output)
                        self.output = None
                    raise

    async def _forward_forever(self):
        while True:
            await self._forward_pending()
            await asyncio.sleep(0.02)

    async def _run(self):
        # Publications are fenced separately from the ownership health poll.
        while True:
            try:
                await self._run_owned()
            except Exception:
                await self._stop_workers()
                logger.exception("System ingress interrupted; retrying")
            await asyncio.sleep(5)

    async def _run_owned(self):
        async with get_async_engine().connect() as ownership:
            lease = await WorkerOwnership.acquire(ownership, SYSTEM_INGRESS_LOCK)
            if lease is None:
                return
            self.ownership = lease
            try:
                async with asyncio.TaskGroup() as tasks:
                    tasks.create_task(self._forward_forever())
                    tasks.create_task(self._poll_owned(ownership))
            finally:
                await self._stop_workers()
                if self.output is not None:
                    await close_client(self.output)
                    self.output = None
                with suppress(Exception):
                    await lease.release(ownership)

    async def _poll_owned(self, ownership):
        lease = self.ownership
        if lease is None:
            raise RuntimeError("Ingress has no ownership lease")
        sessions = get_async_session_local()
        while True:
            await ownership.execute(text("SELECT 1"))
            await ownership.commit()
            async with self.effects, sessions() as session:
                await lease.fence(session)
                row = await session.scalar(
                    select(SystemCollectionConfiguration).where(
                        SystemCollectionConfiguration.id == 1
                    )
                )
                if row is not None:
                    definition = await self._step(row)
                    await self._supervise()
                    with self.guard:
                        sources = {
                            key: dict(value) for key, value in self.states.items()
                        }
                        state: IngressWorkerState = {
                            "revision": row.revision,
                            "generation": self.generation,
                            "status": self._status(definition),
                            "sources": sources,
                            "readings": {
                                key: dict(value) for key, value in self.readings.items()
                            },
                            "checked_at": datetime.now(UTC).isoformat(),
                            "last_publish_at": self.last_publish,
                            "dropped": self.dropped,
                        }
                    await session.execute(
                        update(SystemCollectionConfiguration)
                        .where(
                            SystemCollectionConfiguration.id == 1,
                            SystemCollectionConfiguration.revision == row.revision,
                        )
                        .values(ingress_status=state)
                    )
                    await session.commit()
            await asyncio.sleep(2)

    def _status(self, definition) -> str:
        """Applied once this revision's generation is configured and publishing.

        The collector activates a revision when ingress reports it applied, so
        a connected output alone is not enough: until the collector prepares
        the new generation this process still waits to configure it.
        """
        connected = self.output is not None and self.output.is_connected()
        configured = self.generation == definition.generation or not any(
            True for _ in definition.streams(selected_only=True)
        )
        return INGRESS_APPLIED if connected and configured else INGRESS_CONNECTING

    async def _step(self, row):
        definition = SystemCollectionDefinition.model_validate(row.document)
        if self.output is None:
            self.output = await asyncio.to_thread(self._make_output)
        prepared = is_prepared_or_applied(row.collection_status, row.revision)
        if self.generation != definition.generation:
            # Wait until the collector is listening to this unique generation.
            if self.generation is not None:
                await self._stop_workers()
            if prepared and self.output.is_connected():
                await self._configure(definition)
        return definition
