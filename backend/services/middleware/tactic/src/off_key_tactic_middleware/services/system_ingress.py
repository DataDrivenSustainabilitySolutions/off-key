"""Long-lived selected subscriptions forward raw envelopes through internal EMQX.

Admission, sampling, persistence and accepted detector output remain exclusively
owned by mqtt-proxy. No view lease or browser connection controls this worker.
"""

import asyncio
import json
import time
from contextlib import suppress
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from off_key_core.config.logs import logger
from off_key_core.db.base import get_async_engine, get_async_session_local
from off_key_core.db.system import SystemCollectionConfiguration
from off_key_core.schemas.system_collection import SystemCollectionDefinition
from off_key_core.utils.payload_decode import MAX_PAYLOAD_BYTES
from paho.mqtt.client import MQTT_ERR_SUCCESS, Client
from paho.mqtt.enums import CallbackAPIVersion
from sqlalchemy import select, text, update

from ..config.config import get_tactic_settings
from ..config.system_live import get_system_live_settings
from .retired_ingress import retire_v1_ingress
from .system_live_mqtt import LiveMqttWorker

SYSTEM_INGRESS_LOCK = 73128005


class SystemIngress:
    def __init__(self, *, access_resolver=None):
        self.settings = get_system_live_settings()
        self.access_resolver = access_resolver
        self.guard = RLock()
        self.workers = []
        self.states = {}
        self.bindings = {}
        self.readings = {}
        self._received_at_us = {}
        self.generation = None
        self.output = None
        self.task = None
        self.last_publish = None
        self.dropped = 0

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
            await asyncio.to_thread(self.output.disconnect)
            await asyncio.to_thread(self.output.loop_stop)
            self.output = None

    def _make_output(self):
        defaults = get_tactic_settings().config.radar_defaults
        client = Client(
            CallbackAPIVersion.VERSION2, client_id=f"aberration-ingress-{uuid4().hex}"
        )
        client.max_queued_messages_set(512)
        client.max_inflight_messages_set(32)
        client.reconnect_delay_set(1, 30)
        if defaults.mqtt_use_auth:
            client.username_pw_set(
                self.settings.SYSTEM_COLLECTION_MQTT_USERNAME or defaults.mqtt_username,
                self.settings.SYSTEM_COLLECTION_MQTT_API_KEY.get_secret_value(),
            )
        if defaults.mqtt_use_tls:
            client.tls_set(ca_certs=self.settings.SYSTEM_COLLECTION_MQTT_CA_FILE)
        client.connect_async(defaults.mqtt_broker_host, defaults.mqtt_broker_port, 30)
        client.loop_start()
        return client

    async def _stop_workers(self):
        with self.guard:
            workers, self.workers = self.workers, []
            self.generation = None
            self.bindings = {}
            self.states = {}
            self.readings = {}
        await asyncio.gather(
            *(asyncio.to_thread(item.stop) for item in workers), return_exceptions=True
        )

    async def _configure(self, definition):
        await self._stop_workers()
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
            for connection in definition.sources:
                topics = self.bindings.get(connection.id)
                if not topics:
                    continue
                self._connect(connection, topics, definition.generation)

    def _connect(self, connection, topics, generation):
        access = self.access_resolver(connection) if self.access_resolver else None
        state = {"state": "connecting", "message": None}
        self.states[connection.id] = state
        if not self.settings.allows_host(connection.host) and access is None:
            state.update(
                state="blocked",
                message="Broker access is not configured by the operator.",
            )
            return
        credential = self.settings.SYSTEM_LIVE_CREDENTIALS.get(
            connection.credential_ref
        )
        if connection.credential_ref and credential is None:
            state.update(
                state="blocked",
                message="Broker credentials are not configured by the operator.",
            )
            return
        if credential is None and access:
            credential = access.credential
        proxy = self.settings.SYSTEM_LIVE_SOCKS_PROXIES.get(connection.host)
        if proxy is None and access:
            proxy = access.proxy
        if access and access.require_tls:
            connection = connection.model_copy(update={"tls": True})
        try:
            worker = LiveMqttWorker(
                connection,
                list(topics),
                credential,
                lambda topic, payload, retained: self._receive(
                    generation, connection.id, topic, payload, retained
                ),
                lambda phase, message: self._state(
                    generation, connection.id, phase, message
                ),
                proxy=proxy,
            )
            self.workers.append(worker)
            worker.start()
        except Exception:
            state.update(
                state="error", message="Broker connection could not be initialized."
            )

    def _state(self, generation, connection_id, phase, message):
        with self.guard:
            if generation == self.generation:
                self.states[connection_id].update(state=phase, message=message)

    def _receive(self, generation, connection_id, topic, payload, retained):
        with self.guard:
            if (
                generation != self.generation
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
                envelope = json.dumps(
                    {
                        "payload": decoded,
                        "received_at": received_at_us / 1000,
                        "upstream_retained": retained,
                    }
                )
            except UnicodeError:
                self.dropped += 1
                return
            for stream in streams:
                result = self.output.publish(
                    stream.ingress_topic, envelope, qos=1, retain=False
                )
                if result.rc == MQTT_ERR_SUCCESS:
                    self.last_publish = datetime.now(UTC).isoformat()
                    if not retained:
                        self.readings[stream.definition.id] = {
                            "fresh_received_at": datetime.fromtimestamp(
                                received_at_us / 1_000_000, UTC
                            ).isoformat()
                        }
                else:
                    self.dropped += 1

    async def _run(self):
        # The ownership connection is held for the whole worker lifetime. Losing
        # it stops subscriptions before a replacement can ingest concurrently.
        while True:
            try:
                await self._run_owned()
            except Exception:
                await self._stop_workers()
                logger.exception("System ingress interrupted; retrying")
            await asyncio.sleep(5)

    async def _run_owned(self):
        async with get_async_engine().connect() as ownership:
            if not await ownership.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": SYSTEM_INGRESS_LOCK}
            ):
                return
            await ownership.commit()
            try:
                await retire_v1_ingress()
                await self._poll_owned(ownership)
            finally:
                await self._stop_workers()
                with suppress(Exception):
                    await ownership.execute(
                        text("SELECT pg_advisory_unlock(:key)"),
                        {"key": SYSTEM_INGRESS_LOCK},
                    )

    async def _poll_owned(self, ownership):
        sessions = get_async_session_local()
        while True:
            await ownership.execute(text("SELECT 1"))
            await ownership.commit()
            async with sessions() as session:
                row = await session.scalar(
                    select(SystemCollectionConfiguration).where(
                        SystemCollectionConfiguration.id == 1
                    )
                )
                if row is not None:
                    await self._step(row)
                    with self.guard:
                        sources = {
                            key: dict(value) for key, value in self.states.items()
                        }
                        state = {
                            "revision": row.revision,
                            "generation": self.generation,
                            "status": "applied"
                            if self.output.is_connected()
                            else "connecting",
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

    async def _step(self, row):
        definition = SystemCollectionDefinition.model_validate(row.document)
        if self.output is None:
            self.output = await asyncio.to_thread(self._make_output)
        prepared = row.collection_status.get(
            "revision"
        ) == row.revision and row.collection_status.get("status") in {
            "prepared",
            "applied",
        }
        if self.generation != definition.generation:
            # Wait until the collector is listening to this unique generation.
            if self.generation is not None:
                await self._stop_workers()
            if prepared and self.output.is_connected():
                await self._configure(definition)
