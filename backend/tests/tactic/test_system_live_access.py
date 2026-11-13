"""Operator broker routes give the preview private access to covered hosts."""

import json
from unittest.mock import MagicMock

import pytest
from off_key_core.schemas.collection_policy import CollectionPolicy
from off_key_core.schemas.system import SystemDocument, SystemSnapshot
from off_key_core.schemas.system_collection import (
    SystemCollectionDefinition,
    build_bindings,
)
from off_key_tactic_middleware.config.system_live import SystemLiveSettings
from off_key_tactic_middleware.domain import ValidationError as DomainValidationError
from off_key_tactic_middleware.services.catalogue import system_collection
from off_key_tactic_middleware.services.catalogue.broker_access import (
    BrokerRouteAccess,
)
from off_key_tactic_middleware.services.catalogue.system_live import SystemLiveService
from pydantic import ValidationError

from tests.support.system_live import FakeWorker


def snapshot(*, host, credential_ref=None):
    return SystemSnapshot(
        revision=1,
        storage_origin="saved",
        document=SystemDocument(
            connections=[
                {
                    "id": "broker",
                    "label": "Broker",
                    "host": host,
                    "credential_ref": credential_ref,
                }
            ],
            streams=[
                {
                    "id": "value",
                    "label": "Value",
                    "connection_id": "broker",
                    "topic": "sensor/value",
                }
            ],
        ),
    )


def route(**overrides):
    return {
        "name": "partner",
        "hosts": ["route-broker"],
        "socks_proxy": {"host": "broker-route", "port": 1055},
        "credential": {"username": "operator", "password": "private-password"},
        **overrides,
    }


def provider(*routes):
    return BrokerRouteAccess(
        SystemLiveSettings(SYSTEM_BROKER_ROUTES=json.dumps(list(routes or [route()])))
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("require_tls", [True, False])
async def test_preview_reaches_covered_hosts_through_the_route(
    require_tls,
):
    worker_factory = MagicMock()
    service = SystemLiveService(
        SystemLiveSettings(SYSTEM_LIVE_ENABLED=True),
        worker_factory=worker_factory,
        access_resolver=provider(route(require_tls=require_tls)),
    )
    saved = snapshot(host="route-broker")
    original = saved.model_dump_json()
    try:
        lease = await service.acquire(saved, 1, 1)
        arguments, options = worker_factory.call_args
        assert options["proxy"].host == "broker-route"
        assert options["proxy"].port == 1055
        assert arguments[2].username == "operator"
        assert arguments[2].password.get_secret_value() == "private-password"
        assert arguments[0].host == "route-broker"
        assert arguments[0].tls is require_tls
        assert saved.model_dump_json() == original
        assert "private-password" not in json.dumps(lease)
        assert "broker-route" not in json.dumps(lease)
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_provider_does_not_approve_other_hosts_or_missing_explicit_credentials():
    for saved in [
        snapshot(host="unapproved"),
        snapshot(host="route-broker", credential_ref="unconfigured"),
    ]:
        service = SystemLiveService(
            SystemLiveSettings(SYSTEM_LIVE_ENABLED=True),
            worker_factory=MagicMock(),
            access_resolver=provider(),
        )
        try:
            lease = await service.acquire(saved, 1, 1)
            assert lease["telemetry"]["connections"][0]["state"] == "blocked"
            assert not service.workers
        finally:
            await service.stop()


def connection(host, **fields):
    return snapshot(host=host).document.connections[0].model_copy(update=fields)


def test_suffixes_match_whole_labels_and_the_first_route_wins():
    access = provider(
        route(name="direct", hosts=["route-broker"], socks_proxy=None),
        route(name="tunnel", hosts=[], host_suffixes=[".mesh.example"]),
    )
    assert access(connection("route-broker")).proxy is None
    assert access(connection("a.mesh.example")).proxy.host == "broker-route"
    assert access(connection("xmesh.example")) is None
    assert access(connection("mesh.example")) is None


def test_routed_websocket_brokers_are_not_tunnelled():
    access = provider()
    assert access(connection("route-broker", transport="websocket")) is None
    direct = provider(route(socks_proxy=None))
    assert direct(connection("route-broker", transport="websocket")) is not None


def test_no_routes_grant_no_access():
    assert BrokerRouteAccess(SystemLiveSettings())(connection("a.ts.net")) is None


@pytest.mark.parametrize(
    "invalid",
    [
        route(hosts=[], host_suffixes=[]),
        route(host_suffixes=["example.net"]),
        route(hosts=["https://broker"]),
        route(socks_proxy={"host": "proxy", "port": 70000}),
        route(name="Not A Name"),
        route(extra=True),
    ],
)
def test_invalid_routes_fail_closed(invalid):
    with pytest.raises(ValidationError):
        SystemLiveSettings(SYSTEM_BROKER_ROUTES=json.dumps([invalid]))


def test_route_names_are_unique():
    with pytest.raises(ValidationError):
        SystemLiveSettings(SYSTEM_BROKER_ROUTES=json.dumps([route(), route()]))


@pytest.mark.asyncio
async def test_simulated_origin_is_explicit_in_telemetry():
    service = SystemLiveService(SystemLiveSettings(SYSTEM_LIVE_DATA_SOURCE="simulated"))
    assert service.snapshot(0)["data_source"] == "simulated"


def test_routes_load_from_the_mounted_secret_file(tmp_path):
    (tmp_path / "SYSTEM_BROKER_ROUTES").write_text(
        json.dumps([route(hosts=[], host_suffixes=[".mesh.example"])])
    )
    settings = SystemLiveSettings(_secrets_dir=tmp_path)
    access = BrokerRouteAccess(settings)(
        snapshot(host="charger.mesh.example").document.connections[0]
    )
    assert access.proxy.host == "broker-route"
    assert access.credential.username == "operator"


def collection_definition(host):
    document = snapshot(host=host).document.model_copy(deep=True)
    document.streams[0].policy = CollectionPolicy(mode="original")
    return SystemCollectionDefinition(
        document=document, bindings=build_bindings(document), generation="test"
    )


def test_saving_a_recorded_reading_accepts_only_routed_or_allowed_brokers(
    monkeypatch,
):
    settings = SystemLiveSettings(
        SYSTEM_BROKER_ROUTES=json.dumps([route(hosts=["route-broker"])])
    )
    monkeypatch.setattr(system_collection, "get_system_live_settings", lambda: settings)
    validate = system_collection.SystemCollectionService._validate_access
    validate(collection_definition("route-broker"))
    with pytest.raises(DomainValidationError, match="allowlist"):
        validate(collection_definition("unrouted-broker"))


def http_snapshot(policy=None):
    return SystemSnapshot(
        revision=1,
        storage_origin="saved",
        document=SystemDocument(
            connections=[
                {
                    "id": "api",
                    "label": "API",
                    "protocol": "http",
                    "host": "api.example.com",
                    "tls": True,
                }
            ],
            streams=[
                {
                    "id": "temperature",
                    "label": "Temperature",
                    "connection_id": "api",
                    "topic": "/v1/status",
                    "payload_pointer": "/temperature",
                    "policy": policy,
                }
            ],
        ),
    )


class PollingWorker(FakeWorker):
    def __init__(self, *arguments, interval, **options):
        super().__init__(*arguments, **options)
        self.interval = interval


@pytest.mark.asyncio
@pytest.mark.parametrize(("minimum", "interval"), [(1, 5), (30, 30)])
async def test_an_http_source_is_previewed_by_polling_its_paths(minimum, interval):
    service = SystemLiveService(
        SystemLiveSettings(
            SYSTEM_LIVE_ENABLED=True,
            SYSTEM_HTTP_ALLOWED_ORIGINS=["https://api.example.com"],
            SYSTEM_HTTP_MIN_POLL_SECONDS=minimum,
        ),
        worker_factory=None,
        http_worker_factory=PollingWorker,
    )
    try:
        await service.acquire(http_snapshot(), 1, 1)
        (worker,) = service.workers
        assert (worker.topics, worker.interval) == (["/v1/status"], interval)
        assert worker.connection.port == 443

        worker.message("/v1/status", b'{"temperature": "21.5"}', False)
        (reading,) = service.snapshot(0)["streams"]
        assert (reading["value"], reading["decode_errors"]) == (21.5, 0)
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_an_http_preview_needs_an_allowed_origin():
    service = SystemLiveService(
        SystemLiveSettings(
            SYSTEM_LIVE_ENABLED=True, SYSTEM_LIVE_ALLOWED_HOSTS=["api.example.com"]
        ),
        http_worker_factory=MagicMock(),
        access_resolver=provider(route(hosts=["api.example.com"])),
    )
    try:
        lease = await service.acquire(http_snapshot(), 1, 1)
        (state,) = lease["telemetry"]["connections"]
        assert (state["state"], state["message"]) == (
            "blocked",
            "The server is not in the operator's HTTP origin allowlist.",
        )
        assert not service.workers
    finally:
        await service.stop()


def test_recording_an_http_reading_needs_an_allowed_origin(monkeypatch):
    definition = SystemCollectionDefinition(
        document=http_snapshot(CollectionPolicy(mode="sample")).document,
        bindings=build_bindings(http_snapshot().document),
        generation="test",
    )
    validate = system_collection.SystemCollectionService._validate_access
    monkeypatch.setattr(
        system_collection,
        "get_system_live_settings",
        lambda: SystemLiveSettings(SYSTEM_LIVE_ALLOWED_HOSTS=["api.example.com"]),
    )
    with pytest.raises(DomainValidationError, match="HTTP origin allowlist"):
        validate(definition)

    monkeypatch.setattr(
        system_collection,
        "get_system_live_settings",
        lambda: SystemLiveSettings(
            SYSTEM_HTTP_ALLOWED_ORIGINS=["https://api.example.com"]
        ),
    )
    validate(definition)
