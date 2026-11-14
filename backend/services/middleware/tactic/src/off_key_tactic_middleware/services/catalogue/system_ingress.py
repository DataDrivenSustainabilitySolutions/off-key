"""Long-lived selected subscriptions and polls forward raw envelopes through
internal EMQX.

Admission, sampling, persistence and accepted detector output remain exclusively
owned by mqtt-proxy. No view lease or browser connection controls this worker.
"""

import asyncio
import json
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from off_key_core.config.logs import logger
from off_key_core.db.base import get_async_engine, get_async_session_local
from off_key_core.db.locks import SYSTEM_INGRESS_LOCK
from off_key_core.db.system import SystemCollectionConfiguration
from off_key_core.db.worker_ownership import WorkerOwnership
from off_key_core.schemas.collection_policy import CollectionPolicy
from off_key_core.schemas.collection_status import (
    INGRESS_APPLIED,
    INGRESS_CONNECTING,
    IngressWorkerState,
    is_prepared_or_applied,
)
from off_key_core.schemas.collection_wire import encode_ingress_envelope
from off_key_core.schemas.system_collection import SystemCollectionDefinition
from off_key_core.utils.arrival_cadence import ArrivalCadence
from off_key_core.utils.mqtt_lifecycle import close_client
from off_key_core.utils.payload_decode import MAX_PAYLOAD_BYTES, resolve_pointer
from paho.mqtt.client import MQTT_ERR_SUCCESS, Client
from paho.mqtt.enums import CallbackAPIVersion
from sqlalchemy import select, text, update

from ...config.config import get_tactic_settings
from ...config.system_live import get_system_live_settings
from .broker_access import ResolvedHttpSource, peer, resolve_broker
from .system_live_http import HttpPollWorker
from .system_live_mqtt import LiveMqttWorker

# A deadline that has always passed: the broker's client gave up after a refusal.
REFUSED = float("-inf")
# The API asks the ingress, which runs in the worker, to retry a broker now by
# sending the broker's id on this channel (SystemService.request_reconnect).
RECONNECT_CHANNEL = "off_key_ingress_reconnect"
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
    # Readings whose source timestamp did not change with this reply, and the
    # timestamp of each other reading that names one (None where unreadable).
    unchanged: frozenset = frozenset()
    stamps: dict = field(default_factory=dict)


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
        # Per HTTP reading: the source timestamp of the reply forwarded last, and
        # the newest reply with another timestamp that still waits to be forwarded.
        self.source_stamps = {}
        self.waiting_stamps = {}
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
        self.reconnects: set[asyncio.Task] = set()

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
            self.waiting_stamps = {}
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
            stamped = {
                stream.definition.id
                for stream in definition.streams(selected_only=True)
                if stream.definition.timestamp_pointer is not None
            }
            self.source_stamps = {
                key: stamp
                for key, stamp in self.source_stamps.items()
                if key in stamped
            }
            for connection in definition.document.connections:
                topics = self.bindings.get(connection.id)
                if not topics:
                    continue
                self._connect(connection, topics, definition.generation)

    def _connect(self, connection, topics, generation, *, quiet=False):
        """Start one source client; a quiet retry keeps the reported failure
        until the source is connected again."""
        source = peer(connection).capitalize()
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
                message=f"{source} access is not configured by the operator.",
            )
            return
        if resolved == "credential_missing":
            state.update(
                state="blocked",
                message=f"{source} credentials are not configured by the operator.",
            )
            return
        connection = resolved.connection
        attempt = object()

        def receive(topic, payload, retained):
            self._receive(generation, connection.id, topic, payload, retained, attempt)

        def report(phase, message):
            self._state(generation, connection.id, phase, message, attempt)

        try:
            if isinstance(resolved, ResolvedHttpSource):
                worker = HttpPollWorker(
                    connection,
                    self._poll_intervals(topics),
                    resolved.credential,
                    receive,
                    report,
                    proxy=resolved.proxy,
                )
            else:
                worker = LiveMqttWorker(
                    connection,
                    list(topics),
                    resolved.credential,
                    receive,
                    report,
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
                state="error",
                message=f"{source} connection could not be initialized.",
            )

    def _poll_intervals(self, topics):
        """How often each request path is asked: as often as its most frequent
        recorded reading samples, within the operator's limit. A reading set to
        every message has no rate of its own and uses the default interval."""
        fallback = CollectionPolicy().interval_seconds
        return {
            address: max(
                self.settings.SYSTEM_HTTP_MIN_POLL_SECONDS,
                min(stream.policy.cadence or fallback for stream in streams),
            )
            for address, streams in topics.items()
        }

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
                source = peer(self.sources[connection_id][0])
                if refused:
                    fallback = f"The {source} refused the connection."
                    message = f"{state['message'] or fallback} {RETRY_HINT}"
                else:
                    message = (
                        f"Could not reach the {source} within {timeout} seconds, "
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
            unchanged, stamps = self._source_stamps(decoded, streams)
            if len(unchanged) == len(streams):
                return  # The source measured nothing new since the last poll.
            item = PendingMessage(
                generation,
                connection_id,
                attempt,
                topic,
                envelope,
                size,
                received_at_us / 1_000_000,
                retained,
                unchanged,
                stamps,
            )
            self.pending.append(item)
            self.pending_bytes += size
            self.waiting_stamps.update(dict.fromkeys(stamps, item))

    def _source_stamps(self, decoded, streams) -> tuple[frozenset, dict]:
        """The readings whose source timestamp in this reply equals the one of
        the reply before it, and the timestamp of each other reading that names
        one. A reply without a readable timestamp counts as new."""
        stamped = [
            stream
            for stream in streams
            if stream.definition.timestamp_pointer is not None
        ]
        if not stamped:
            return frozenset(), {}
        try:
            document = json.loads(decoded)
        except (ValueError, RecursionError):
            return frozenset(), {}
        unchanged, stamps = set(), {}
        for stream in stamped:
            identity = stream.definition.id
            try:
                stamp = resolve_pointer(document, stream.definition.timestamp_pointer)
            except (KeyError, IndexError, TypeError, ValueError):
                stamp = None
            if isinstance(stamp, bool) or not isinstance(stamp, (str, int, float)):
                stamp = None
            # The reply before this one is the newest that waits, else the last
            # that was forwarded.
            waiting = self.waiting_stamps.get(identity)
            last = (
                self.source_stamps.get(identity)
                if waiting is None
                else waiting.stamps[identity]
            )
            if stamp is not None and stamp == last:
                unchanged.add(identity)
            else:
                stamps[identity] = stamp
        return frozenset(unchanged), stamps

    def _settle(self, item, *, forwarded):
        """A reply left the queue. Its source timestamps become the last
        forwarded ones only if it reached the internal broker; a reply that did
        not is recorded when a later poll returns the measurement again."""
        with self.guard:
            for identity, stamp in item.stamps.items():
                if self.waiting_stamps.get(identity) is item:
                    del self.waiting_stamps[identity]
                if not forwarded:
                    continue
                if stamp is None:
                    self.source_stamps.pop(identity, None)
                else:
                    self.source_stamps[identity] = stamp

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
        taken = []
        try:
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
                        self._settle(item, forwarded=False)
                        continue
                    taken.append(item)
                    streams = [
                        stream
                        for stream in self.bindings.get(item.connection_id, {}).get(
                            item.topic, []
                        )
                        if stream.definition.id not in item.unchanged
                    ]
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
        except BaseException:
            for item in taken:
                self._settle(item, forwarded=False)
            raise
        with self.guard:
            for item in taken:
                self._settle(item, forwarded=True)
            self._record_arrivals(accepted)

    def _record_arrivals(self, accepted):
        """Note when each forwarded reading arrived fresh, and how often it does."""
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
            stop_listening = await self._listen_for_reconnects(ownership)
            try:
                async with asyncio.TaskGroup() as tasks:
                    tasks.create_task(self._forward_forever())
                    tasks.create_task(self._poll_owned(ownership))
            finally:
                with suppress(Exception):
                    await stop_listening()
                await self._stop_workers()
                if self.output is not None:
                    await close_client(self.output)
                    self.output = None
                with suppress(Exception):
                    await lease.release(ownership)

    async def _listen_for_reconnects(self, ownership):
        """Retry a broker when the API asks, on the connection that holds the lease.

        Only the owner listens, so a request reaches the one process recording.
        The ownership poll commits every two seconds, which starts the LISTEN.
        """
        driver = (await ownership.get_raw_connection()).driver_connection
        loop = asyncio.get_running_loop()

        def requested(_connection, _pid, _channel, connection_id):
            task = loop.create_task(self.reconnect(connection_id))
            self.reconnects.add(task)
            task.add_done_callback(self.reconnects.discard)

        await driver.add_listener(RECONNECT_CHANNEL, requested)

        async def stop_listening():
            await driver.remove_listener(RECONNECT_CHANNEL, requested)

        return stop_listening

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
