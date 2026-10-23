"""Apply catalog collection policy before persistence and accepted MQTT output."""

import asyncio
import signal
import time
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime

from off_key_core.config.logs import logger
from off_key_core.db.base import get_async_engine, get_async_session_local
from off_key_core.db.collection import (
    COLLECTION_PROXY_LOCK,
)
from off_key_core.db.collection_runtime import read_collection_runtime
from off_key_core.db.models import Charger, CollectionState
from off_key_core.db.system import SystemCollectionConfiguration
from off_key_core.schemas.collection_status import (
    COLLECTION_APPLIED,
    COLLECTION_APPLYING,
    COLLECTION_DISABLED,
    COLLECTION_ERROR,
    COLLECTION_PREPARED,
    COLLECTION_STARTING,
    CollectionWorkerState,
    is_applied,
)
from off_key_core.schemas.system_collection import runtime_fingerprint
from sqlalchemy import case, delete, text, update
from sqlalchemy.dialects.postgresql import insert

from .client.facade import MQTTClient
from .collection_buffer import CollectionBuffer
from .collection_diagnostics import CollectionDiagnostics
from .config.config import get_mqtt_settings
from .telemetry import DatabaseWriter


class MQTTProxyService:
    def __init__(self):
        self.config = get_mqtt_settings().config
        self.mqtt_client = MQTTClient(self.config)
        self.buffer = CollectionBuffer(self.config.max_message_queue_size)
        self.mqtt_client.set_message_handler(self.buffer.receive)
        self.session_factory = get_async_session_local()
        self.database_writer = DatabaseWriter(
            self.config, self.session_factory, self.config.build_topic_extractor()
        )
        self.shutdown_event = asyncio.Event()
        self.is_running = False
        self.revision = -1
        self._prepared_revision = -1
        self._prepared_configuration: list | None = None
        self._generation = -1
        self.state: CollectionWorkerState = {"status": COLLECTION_STARTING}
        self._task: asyncio.Task | None = None
        self.diagnostics = CollectionDiagnostics(self.buffer, self.database_writer)

    async def start(self):
        if self._task is None:
            self.is_running = True
            self._task = asyncio.create_task(self._collect(), name="catalog-collection")

    async def _apply(self, snapshot) -> None:
        self.buffer.pause()
        self.state = {"revision": snapshot.revision, "status": COLLECTION_APPLYING}
        await self._save_status(snapshot.revision)
        async with asyncio.timeout(self.config.graceful_shutdown_timeout):
            await self.database_writer.drain()
            await self.mqtt_client.drain_publishes()
        # This is a cache, not history. Rebuild it from the selected bindings so
        # removed or remapped sensors cannot expose values from an earlier revision.
        async with self.session_factory() as session:
            await session.execute(delete(CollectionState))
            await session.commit()
        subscriptions = self.mqtt_client.subscription_manager
        desired = {
            s.ingress_topic for s in snapshot.catalog.streams(selected_only=True)
        }
        for topic in subscriptions.get_all_topics() - desired:
            if not await self.mqtt_client.unsubscribe(topic):
                raise RuntimeError("Broker did not acknowledge a removed subscription")
        try:
            for topic in desired - subscriptions.get_subscriptions():
                if not await self.mqtt_client.subscribe(topic, qos=0):
                    raise RuntimeError(
                        "Broker did not acknowledge a selected subscription"
                    )
        except BaseException:
            self.buffer.pause()
            raise
        self._prepared_revision = snapshot.revision
        self._prepared_configuration = runtime_fingerprint(snapshot.catalog)
        self._generation = subscriptions.generation
        self.state = {
            "revision": snapshot.revision,
            "status": COLLECTION_PREPARED,
            "selected_sensors": len(desired),
            "idle": not desired,
        }
        await self._save_status(snapshot.revision)

    async def _refresh_configuration(self) -> None:
        async with self.session_factory() as session:
            snapshot = await read_collection_runtime(session)
        if not self.mqtt_client.is_connected:
            self.buffer.pause()
            self.revision = self._prepared_revision = -1
            if self.mqtt_client.state.value != "connecting":
                await self.mqtt_client.connect()
            if not self.mqtt_client.is_connected:
                raise RuntimeError("Local MQTT broker is disconnected")
        if (
            self._prepared_revision >= 0
            and self._prepared_revision != snapshot.revision
            and self._generation == self.mqtt_client.subscription_manager.generation
            and self._prepared_configuration == runtime_fingerprint(snapshot.catalog)
        ):
            # Names do not affect admission, routes, retained state or sampling
            # deadlines. Adopt their revision without closing a running collector.
            previous = self._prepared_revision
            self._prepared_revision = snapshot.revision
            if self.revision == previous:
                self.revision = snapshot.revision
            self.state["revision"] = snapshot.revision
        if (
            self._prepared_revision != snapshot.revision
            or self._generation != self.mqtt_client.subscription_manager.generation
        ):
            self.revision = -1
            await self._apply(snapshot)
        ingress_ready = is_applied(snapshot.ingress, snapshot.revision)
        if self.revision != snapshot.revision and (
            ingress_ready or not snapshot.catalog.streams(selected_only=True)
        ):
            self.buffer.configure(snapshot.catalog)
            # Re-request retained snapshots only after routes match this revision.
            for stream in snapshot.catalog.streams(selected_only=True):
                if not await self.mqtt_client.subscribe(stream.ingress_topic, qos=0):
                    raise RuntimeError(
                        "Broker did not acknowledge collection activation"
                    )
            self.revision = snapshot.revision
            self.state["status"] = COLLECTION_APPLIED
        await self._save_status(snapshot.revision)

    async def _save_status(self, revision: int | None) -> None:
        self.state["checked_at"] = datetime.now(UTC).isoformat()
        self.state["counters"] = self.buffer.metrics()
        self.state["records_written"] = self.database_writer.total_records_written
        self.state["diagnostics"] = self.diagnostics.snapshot(
            connected=self.mqtt_client.is_connected
        )
        async with self.session_factory() as session:
            await session.execute(
                update(SystemCollectionConfiguration)
                .where(
                    SystemCollectionConfiguration.id == 1,
                    SystemCollectionConfiguration.revision == revision,
                )
                .values(collection_status=self.state.copy())
            )
            await session.commit()

    async def _emit(self) -> None:
        observations = self.buffer.take()
        states = {}
        live_seen = {}
        for observation in observations:
            message = observation.message()
            if not observation.snapshot:
                charger_id = observation.stream.charger_id
                live_seen[charger_id] = max(
                    live_seen.get(charger_id, observation.received_at),
                    observation.received_at,
                )
            if observation.stream.value_type == "number" and not observation.snapshot:
                # Bounded DB writer applies backpressure before publishing downstream.
                async with asyncio.timeout(self.config.graceful_shutdown_timeout):
                    await self.database_writer.write_record(
                        observation.telemetry_record()
                    )
                if not await self.mqtt_client.publish(
                    message.topic, message.payload, qos=1
                ):
                    self.buffer.count("publish_failed")
            states[(observation.stream.charger_id, observation.stream.key)] = {
                "charger_id": observation.stream.charger_id,
                "sensor_key": observation.stream.key,
                "value": observation.value,
                "received_at": observation.received_at,
                "is_snapshot": observation.snapshot,
            }
        if states:
            statement = insert(CollectionState).values(list(states.values()))
            statement = statement.on_conflict_do_update(
                index_elements=["charger_id", "sensor_key"],
                set_={
                    key: getattr(statement.excluded, key)
                    for key in ("value", "received_at", "is_snapshot")
                },
                where=statement.excluded.received_at >= CollectionState.received_at,
            )
            async with self.session_factory() as session:
                await session.execute(statement)
                if live_seen:
                    # State-only observations establish contact too. Retained
                    # snapshots and older observations must not refresh liveness.
                    timestamp = case(live_seen, value=Charger.charger_id)
                    await session.execute(
                        update(Charger)
                        .where(
                            Charger.charger_id.in_(live_seen),
                            Charger.mqtt_last_message.is_(None)
                            | (Charger.mqtt_last_message <= timestamp),
                        )
                        .values(
                            online=True,
                            mqtt_connected=True,
                            mqtt_last_message=timestamp,
                            last_seen=case(
                                {
                                    key: value.isoformat()
                                    for key, value in live_seen.items()
                                },
                                value=Charger.charger_id,
                            ),
                        )
                    )
                await session.commit()
            self.diagnostics.last_state_write_at = datetime.now(UTC)

    async def _collect(self) -> None:
        if not self.config.enabled:
            self.state = {"status": COLLECTION_DISABLED}
            await self.shutdown_event.wait()
            return
        # Losing this DB connection terminates the worker; it cannot continue as
        # an unfenced second collector after a replacement acquires the lock.
        async with get_async_engine().connect() as ownership:
            if not await ownership.scalar(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": COLLECTION_PROXY_LOCK},
            ):
                raise RuntimeError("Another collection worker owns this database")
            await ownership.commit()
            completed = False
            try:
                await self.database_writer.start()
                await self._collect_owned(ownership)
                completed = True
            finally:
                self.buffer.pause()
                # A failed ownership connection cannot safely drain after another
                # worker acquires the lock. Cancel remaining work in that case.
                await self.database_writer.stop(drain=completed)
                if not completed:
                    await self.mqtt_client.disconnect()
                with suppress(Exception):
                    await ownership.execute(
                        text("SELECT pg_advisory_unlock(:key)"),
                        {"key": COLLECTION_PROXY_LOCK},
                    )

    async def _collect_owned(self, ownership) -> None:
        next_poll = 0.0
        while not self.shutdown_event.is_set():
            poll = time.monotonic() >= next_poll
            if poll:
                # A lost ownership connection must terminate, not enter the
                # ordinary reconciliation retry path below.
                await ownership.execute(text("SELECT 1"))
                await ownership.commit()
                next_poll = time.monotonic() + 2
            try:
                if poll:
                    await self._refresh_configuration()
                if self.revision >= 0 and self.mqtt_client.is_connected:
                    await self._emit()
            except Exception:
                self.buffer.pause()
                self.revision = self._prepared_revision = -1
                self.state = {
                    "revision": self.state.get("revision"),
                    "status": COLLECTION_ERROR,
                    "error": "Collection could not be applied or written; retrying",
                }
                with suppress(Exception):
                    await self._save_status(self.state["revision"])
                logger.exception("Collection failed")
            await asyncio.sleep(0.1)

    async def stop(self):
        self.shutdown_event.set()
        self.buffer.pause()
        try:
            if self._task:
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._task),
                        self.config.graceful_shutdown_timeout,
                    )
                finally:
                    if not self._task.done():
                        self._task.cancel()
                    with suppress(asyncio.CancelledError):
                        await self._task
        finally:
            await self.mqtt_client.disconnect()
            self.is_running = False

    async def run(self):
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, self.shutdown_event.set)
        try:
            await self.start()
            if self._task is None:
                raise RuntimeError("Collection loop did not start")
            await self._task
        finally:
            await self.stop()

    def get_readiness_status(self) -> dict:
        ready = bool(
            self.is_running
            and self._task
            and not self._task.done()
            and self.mqtt_client.is_connected
            and self.state.get("status") == COLLECTION_APPLIED
        )
        return {"ready": ready, "service": "mqtt-proxy", **self.state}

    def get_health_status(self) -> dict:
        return {
            **self.get_readiness_status(),
            "counters": self.buffer.metrics(),
            "database_writer": asdict(self.database_writer.get_health_status()),
            "diagnostics": self.diagnostics.snapshot(
                connected=self.mqtt_client.is_connected
            ),
        }
