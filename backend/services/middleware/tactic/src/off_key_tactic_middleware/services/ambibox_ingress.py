"""Reconcile AmbiBox routes and EMQX ingress from the saved catalog."""

import asyncio
import base64
import json
from contextlib import suppress
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import UUID

from off_key_core.config.logs import logger
from off_key_core.db.base import get_async_engine, get_async_session_local
from off_key_core.db.collection import (
    COLLECTION_INGRESS_LOCK,
    read_collection_configuration,
)
from off_key_core.db.models import CollectionConfiguration
from off_key_core.schemas.collection import AmbiboxCatalog, CatalogSource
from sqlalchemy import text, update

from ..config.collection import AmbiboxSettings, get_ambibox_settings

RESOURCE_PREFIX = "offkey_ambibox_"
CHAIN_NAME = "offkey-ambibox-tailnet"
_NOT_READ = object()


class IngressError(Exception):
    pass


class ManagementApi:
    def __init__(self, url: str, username: str, password: str):
        self.url = url.rstrip("/")
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}"}

    async def request(self, method: str, path: str, payload=None):
        def send():
            request = Request(
                f"{self.url}/{path.lstrip('/')}",
                method=method,
                data=None if payload is None else json.dumps(payload).encode(),
                headers={**self.headers, "Content-Type": "application/json"},
            )
            try:
                with urlopen(request, timeout=10) as response:
                    body = response.read(2 * 1024 * 1024 + 1)
                    if len(body) > 2 * 1024 * 1024:
                        raise ValueError("Management response exceeds limit")
                    return json.loads(body) if body else None
            except HTTPError as exc:
                if exc.code == 404 and (
                    method == "GET"
                    or (
                        method == "DELETE" and path.startswith("mqtt/retainer/message/")
                    )
                ):
                    return None
                # Broker API bodies can contain credentials or submitted configuration.
                raise IngressError(f"Management API returned HTTP {exc.code}") from None
            except (URLError, TimeoutError, ValueError) as exc:
                raise IngressError(
                    "Management API is unavailable or returned invalid data"
                ) from exc

        return await asyncio.to_thread(send)


def configuration_matches(expected, actual) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual
            and (
                (key in {"password", "secret"} and actual[key] == "******")
                or configuration_matches(value, actual[key])
            )
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(expected) == len(actual)
            and all(
                configuration_matches(left, right)
                for left, right in zip(expected, actual, strict=True)
            )
        )
    return expected == actual


def source_resources(
    source: CatalogSource, catalog: AmbiboxCatalog, settings: AmbiboxSettings
) -> tuple[dict, dict, dict, dict]:
    name = RESOURCE_PREFIX + source.id.hex
    enabled = any(
        stream.source_id == str(source.id)
        for stream in catalog.streams(selected_only=True)
    )
    topics = [
        sensor.upstream_topic
        for charger in source.chargers
        for sensor in charger.sensors
    ]
    topic_predicate = (
        "topic IN (" + ", ".join(f"'{topic}'" for topic in topics) + ")"
        if topics
        else "false"
    )
    route = {
        "name": name,
        "addr": f":{source.forward_port}",
        "handler": {"type": "tcp", "chain": CHAIN_NAME},
        "listener": {"type": "tcp"},
        "forwarder": {
            "nodes": [{"name": name, "addr": f"{source.host}:{source.port}"}]
        },
    }
    connector = {
        "type": "mqtt",
        "name": name,
        "enable": enabled,
        "description": f"AmbiBox {source.host}:{source.port}",
        "server": f"{settings.AMBIBOX_FORWARD_HOST}:{source.forward_port}",
        "proto_ver": "v4",
        "clean_start": True,
        "keepalive": "60s",
        "connect_timeout": "10s",
        "retry_interval": "15s",
        "pool_size": 1,
        "username": settings.AMBIBOX_MQTT_USERNAME,
        "password": settings.AMBIBOX_MQTT_PASSWORD.get_secret_value(),
        "ssl": {"enable": settings.AMBIBOX_MQTT_TLS},
    }
    mqtt_source = {
        "type": "mqtt",
        "name": name,
        "enable": enabled,
        "connector": name,
        "parameters": {"topic": "device/evCharger/+/#", "qos": 0},
    }
    rule = {
        "id": name,
        "name": name,
        "enable": enabled,
        "sql": (
            "SELECT topic, payload, retain AS upstream_retained, "
            "message_received_at AS received_at "
            f'FROM "$bridges/mqtt:{name}" WHERE {topic_predicate} '
            "AND strlen(payload) <= 4096"
        ),
        "actions": [
            {
                "function": "republish",
                "args": {
                    "topic": f"ingress/ambibox/{source.id}/${{topic}}",
                    "payload": "${.}",
                    "qos": 0,
                    "retain": True,
                    "direct_dispatch": False,
                },
            }
        ],
    }
    return route, connector, mqtt_source, rule


class AmbiboxIngress:
    def __init__(self, settings: AmbiboxSettings | None = None):
        self.settings = settings or get_ambibox_settings()
        self.emqx = ManagementApi(
            self.settings.AMBIBOX_EMQX_API_URL,
            self.settings.AMBIBOX_EMQX_API_KEY.get_secret_value(),
            self.settings.AMBIBOX_EMQX_API_SECRET.get_secret_value(),
        )
        self.gost = ManagementApi(
            self.settings.AMBIBOX_GOST_API_URL,
            self.settings.AMBIBOX_GOST_USERNAME,
            self.settings.AMBIBOX_GOST_PASSWORD.get_secret_value(),
        )
        self._task: asyncio.Task | None = None
        self._limit = asyncio.Semaphore(4)
        self._credentials_applied: set[str] = set()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="ambibox-ingress")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _upsert_emqx(
        self,
        collection: str,
        identity: str,
        payload: dict,
        *,
        current=_NOT_READ,
        force: bool = False,
    ):
        path = f"{collection}/{quote(identity, safe='')}"
        if current is _NOT_READ:
            current = await self.emqx.request("GET", path)
        if current is None:
            await self.emqx.request("POST", collection, payload)
        elif force or not configuration_matches(payload, current):
            body = {
                key: value
                for key, value in payload.items()
                if key not in {"type", "name", "id"}
            }
            await self.emqx.request("PUT", path, body)
        else:
            return current
        return await self.emqx.request("GET", path)

    async def _ensure_chain(self, gost_config: dict) -> None:
        desired = {
            "name": CHAIN_NAME,
            "hops": [
                {
                    "name": "tailnet",
                    "nodes": [
                        {
                            "name": "tailnet",
                            "addr": self.settings.AMBIBOX_SOCKS_SERVER,
                            "connector": {"type": "socks5"},
                            "dialer": {"type": "tcp"},
                        }
                    ],
                }
            ],
        }
        existing = next(
            (
                chain
                for chain in (gost_config.get("chains") or [])
                if chain["name"] == CHAIN_NAME
            ),
            None,
        )
        if existing is None:
            await self.gost.request("POST", "config/chains", desired)
        elif not configuration_matches(desired, existing):
            await self.gost.request("PUT", f"config/chains/{CHAIN_NAME}", desired)

    async def _reconcile_source(
        self, source: CatalogSource, catalog: AmbiboxCatalog, gost_config: dict
    ) -> dict:
        async with self._limit:
            try:
                route, connector, mqtt_source, rule = source_resources(
                    source, catalog, self.settings
                )
                name = connector["name"]
                connector_path = f"connectors/{quote('mqtt:' + name, safe='')}"
                current_connector = await self.emqx.request("GET", connector_path)
                current_rule = await self.emqx.request("GET", f"rules/{name}")
                existing = next(
                    (
                        item
                        for item in (gost_config.get("services") or [])
                        if item["name"] == name
                    ),
                    None,
                )
                changed_binding = bool(
                    current_connector is not None
                    and current_connector.get("description") != connector["description"]
                )
                changed_topics = bool(
                    current_rule and current_rule.get("sql") != rule["sql"]
                )
                if changed_binding or changed_topics:
                    if current_connector is not None and current_connector["enable"]:
                        await self.emqx.request("PUT", connector_path + "/enable/false")
                        current_connector = {**current_connector, "enable": False}
                    # Keep the old description and SQL until cleanup succeeds, so
                    # a failed purge is retried instead of accepting stale snapshots.
                    await self.emqx.request(
                        "DELETE",
                        "mqtt/retainer/message/"
                        + quote(f"ingress/ambibox/{source.id}/#", safe=""),
                    )
                if existing is None:
                    await self.gost.request("POST", "config/services", route)
                elif not configuration_matches(route, existing):
                    await self.gost.request("PUT", f"config/services/{name}", route)
                # A new connector stays disabled until its rule exists, so the initial
                # retained replay cannot be lost between resource creation requests.
                initial = {**connector, "enable": False}
                if current_connector is None:
                    await self.emqx.request("POST", "connectors", initial)
                    current_connector = initial
                    self._credentials_applied.add(name)
                await self._upsert_emqx("rules", name, rule, current=current_rule)
                source_state = await self._upsert_emqx(
                    "sources", f"mqtt:{name}", mqtt_source
                )
                connector_state = await self._upsert_emqx(
                    "connectors",
                    f"mqtt:{name}",
                    connector,
                    current=current_connector,
                    force=name not in self._credentials_applied,
                )
                self._credentials_applied.add(name)
                connected = (
                    connector_state is not None
                    and connector_state.get("status") == "connected"
                    and source_state is not None
                    and source_state.get("status") == "connected"
                )
                result = {
                    "status": "paused"
                    if not connector["enable"]
                    else "connected"
                    if connected
                    else "connecting",
                    "configured": True,
                }
                if connector["enable"]:
                    metrics = await self.emqx.request(
                        "GET", f"sources/{quote('mqtt:' + name, safe='')}/metrics"
                    )
                    result["metrics"] = metrics.get("metrics", {}) if metrics else {}
                return result
            except IngressError as exc:
                return {"status": "error", "configured": False, "error": str(exc)}

    async def _list_emqx(self, collection: str) -> list[dict]:
        # Only the rules endpoint is paginated. Gather before deleting, otherwise
        # removals shift later pages and can leave obsolete rules active.
        if collection != "rules":
            return await self.emqx.request("GET", collection) or []
        entries = []
        page = 1
        while True:
            response = await self.emqx.request("GET", f"rules?page={page}&limit=100")
            entries.extend(response["data"])
            if not response["meta"]["hasnext"]:
                return entries
            page += 1

    async def _remove_obsolete(self, wanted: set[str], gost_config: dict) -> None:
        for collection in ("rules", "sources", "connectors"):
            entries = await self._list_emqx(collection)
            for entry in entries:
                name = entry.get("name", entry.get("id", ""))
                if name.startswith(RESOURCE_PREFIX) and name not in wanted:
                    identity = name if collection == "rules" else f"mqtt:{name}"
                    if collection == "rules":
                        connector_path = f"connectors/{quote('mqtt:' + name, safe='')}"
                        connector = await self.emqx.request("GET", connector_path)
                        if connector is not None and connector["enable"]:
                            await self.emqx.request(
                                "PUT", connector_path + "/enable/false"
                            )
                        source_id = str(UUID(hex=name.removeprefix(RESOURCE_PREFIX)))
                        topic_filter = f"ingress/ambibox/{source_id}/#"
                        await self.emqx.request(
                            "DELETE",
                            "mqtt/retainer/message/" + quote(topic_filter, safe=""),
                        )
                    await self.emqx.request(
                        "DELETE", f"{collection}/{quote(identity, safe='')}"
                    )
        for entry in gost_config.get("services") or []:
            name = entry["name"]
            if name.startswith(RESOURCE_PREFIX) and name not in wanted:
                await self.gost.request("DELETE", f"config/services/{name}")

    async def reconcile(self, snapshot) -> dict:
        catalog = snapshot.catalog
        if not self.settings.AMBIBOX_INGRESS_ENABLED:
            return {"revision": snapshot.revision, "status": "disabled", "sources": {}}
        gost_config = await self.gost.request("GET", "config")
        if not isinstance(gost_config, dict):
            raise IngressError("GOST did not return its configuration")
        await self._ensure_chain(gost_config)
        wanted = {RESOURCE_PREFIX + source.id.hex for source in catalog.sources}
        self._credentials_applied.intersection_update(wanted)
        await self._remove_obsolete(wanted, gost_config)
        if snapshot.collection.get(
            "revision"
        ) != snapshot.revision or snapshot.collection.get("status") not in {
            "prepared",
            "applied",
        }:
            return {
                "revision": snapshot.revision,
                "status": "waiting_for_collector",
                "sources": {},
            }
        results = await asyncio.gather(
            *(
                self._reconcile_source(source, catalog, gost_config)
                for source in catalog.sources
            )
        )
        return {
            "revision": snapshot.revision,
            "status": "applied"
            if all(result["configured"] for result in results)
            else "error",
            "sources": {
                str(source.id): result
                for source, result in zip(catalog.sources, results, strict=True)
            },
        }

    async def _run(self) -> None:
        while True:
            try:
                await self._run_owned()
            except Exception:
                logger.exception("AmbiBox ingress reconciliation interrupted; retrying")
            await asyncio.sleep(5)

    async def _run_owned(self) -> None:
        session_factory = get_async_session_local()
        async with get_async_engine().connect() as ownership:
            owns_lock = await ownership.scalar(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": COLLECTION_INGRESS_LOCK},
            )
            await ownership.commit()
            if not owns_lock:
                logger.error("Another AmbiBox ingress reconciler is already running")
                return
            try:
                while True:
                    await ownership.execute(text("SELECT 1"))
                    await ownership.commit()
                    async with session_factory() as session:
                        snapshot = await read_collection_configuration(session)
                    try:
                        state = await self.reconcile(snapshot)
                    except IngressError as exc:
                        state = {
                            "revision": snapshot.revision,
                            "status": "error",
                            "error": str(exc),
                        }
                    state["checked_at"] = datetime.now(UTC).isoformat()
                    async with session_factory() as session:
                        await session.execute(
                            update(CollectionConfiguration)
                            .where(
                                CollectionConfiguration.id == 1,
                                CollectionConfiguration.revision == snapshot.revision,
                            )
                            .values(ingress_status=state)
                        )
                        await session.commit()
                    await asyncio.sleep(5)
            finally:
                with suppress(Exception):
                    await ownership.execute(
                        text("SELECT pg_advisory_unlock(:key)"),
                        {"key": COLLECTION_INGRESS_LOCK},
                    )
