from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from off_key_core.db.models import User
from off_key_core.schemas.collection import CatalogSnapshot, SourceProbeRequest
from off_key_core.utils.enum import RoleEnum
from off_key_tactic_middleware.api.v1 import collection
from off_key_tactic_middleware.config.collection import AmbiboxSettings
from off_key_tactic_middleware.domain import InfrastructureError
from off_key_tactic_middleware.services import source_probe

from .test_collection import catalog


@pytest.fixture
def mqtt_probe(monkeypatch):
    client = MagicMock()
    client.subscribe.return_value = (0, 1)
    constructor = MagicMock(return_value=client)
    monkeypatch.setattr(source_probe, "Client", constructor)
    monkeypatch.setattr(source_probe, "PROBE_SECONDS", 2)
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(
        source_probe, "time", SimpleNamespace(monotonic=lambda: clock.now)
    )
    messages = []

    def loop(**kwargs):
        if client.loop.call_count == 1:
            state = constructor.call_args.kwargs["userdata"]
            accepted = SimpleNamespace(is_failure=False)
            client.on_connect(client, state, None, accepted, None)
            client.on_subscribe(client, state, 1, [accepted], None)
            for payload, retained in messages:
                client.on_message(
                    client,
                    state,
                    SimpleNamespace(
                        topic="device/evCharger/0/temperature",
                        payload=payload,
                        retain=retained,
                    ),
                )
        clock.now += 1
        return 0

    client.loop.side_effect = loop
    source = catalog("off").sources[0]
    source.forward_port = 20000
    settings = AmbiboxSettings(AMBIBOX_FORWARD_HOST="forwarder")
    return client, constructor, messages, clock, source, settings


def test_probe_observes_paused_topics_and_keeps_live_over_snapshots(mqtt_probe):
    client, constructor, messages, _, source, settings = mqtt_probe
    messages.extend([(b"12", True), (b"13", False), (b"14", True)])
    result = source_probe.probe_source(source, settings)
    observation = result[str(source.chargers[0].id)]["temperature"]
    assert not observation.is_snapshot
    assert observation.received_at.tzinfo is UTC
    assert set(observation.model_dump()) == {"received_at", "is_snapshot"}
    assert source.chargers[0].policy.mode == "off"
    client.connect.assert_called_once_with("forwarder", 20000)
    client.subscribe.assert_called_once_with([("device/evCharger/0/temperature", 0)])
    assert constructor.call_args.kwargs["clean_session"] is True
    assert constructor.call_args.kwargs["reconnect_on_failure"] is False
    client.disconnect.assert_called_once()


@pytest.mark.parametrize("payload", [b"true", b"NaN", b"{}", b"x" * 4097, b"\xff"])
def test_probe_rejects_readings_collection_would_reject(mqtt_probe, payload):
    client, _, messages, _, source, settings = mqtt_probe
    messages.append((payload, False))
    assert source_probe.probe_source(source, settings) == {}
    client.disconnect.assert_called_once()


def test_probe_returns_snapshots_without_claiming_live_data(mqtt_probe):
    _, _, messages, _, source, settings = mqtt_probe
    messages.append((b"12", True))
    result = source_probe.probe_source(source, settings)
    assert result[str(source.chargers[0].id)]["temperature"].is_snapshot


def test_probe_cleans_up_and_does_not_expose_network_credentials(mqtt_probe):
    client, _, _, _, source, settings = mqtt_probe
    client.connect.side_effect = OSError("secret credentials in network failure")
    with pytest.raises(InfrastructureError, match="Could not connect") as failure:
        source_probe.probe_source(source, settings)
    assert "secret" not in str(failure.value)
    client.disconnect.assert_called_once()


@pytest.mark.parametrize(
    "failure", ["connection", "subscription", "disconnect", "timeout"]
)
def test_probe_reports_failures_instead_of_an_empty_success(mqtt_probe, failure):
    client, constructor, _, clock, source, settings = mqtt_probe

    def fail(**kwargs):
        state = constructor.call_args.kwargs["userdata"]
        rejected = SimpleNamespace(is_failure=True)
        clock.now += 1
        if failure == "connection":
            client.on_connect(client, state, None, rejected, None)
        elif failure == "subscription":
            client.on_subscribe(client, state, 1, [rejected], None)
        return 7 if failure == "disconnect" else 0

    client.loop.side_effect = fail
    with pytest.raises(InfrastructureError):
        source_probe.probe_source(source, settings)
    client.disconnect.assert_called_once()
    assert clock.now <= source_probe.CONNECT_SECONDS


@pytest.fixture
def saved_probe(monkeypatch):
    config = catalog("off")
    config.sources[0].forward_port = 20000
    snapshot = CatalogSnapshot(
        revision=1,
        catalog=config,
        ingress={
            "revision": 1,
            "status": "applied",
            "checked_at": datetime.now(UTC).isoformat(),
            "sources": {str(config.sources[0].id): {"status": "paused"}},
        },
    )
    settings = AmbiboxSettings(AMBIBOX_INGRESS_ENABLED=True)
    monkeypatch.setattr(collection, "get_ambibox_settings", lambda: settings)
    monkeypatch.setattr(
        collection, "read_collection_configuration", AsyncMock(return_value=snapshot)
    )
    probe = MagicMock(return_value={})
    monkeypatch.setattr(collection, "probe_source", probe)
    session = AsyncMock()
    session.scalar.return_value = 1
    return snapshot, settings, probe, session


@pytest.mark.asyncio
async def test_probe_api_allows_a_paused_broker_and_returns_revision(saved_probe):
    snapshot, _, probe, session = saved_probe
    result = await collection.probe_broker(
        snapshot.catalog.sources[0].id,
        SourceProbeRequest(expected_revision=1),
        User(role=RoleEnum.admin),
        session,
    )
    assert result.revision == 1
    assert result.window_seconds == 20
    probe.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["revision", "disabled", "host", "stale", "applying", "port"]
)
async def test_probe_api_checks_revision_and_route_before_connecting(
    saved_probe, failure
):
    snapshot, settings, probe, session = saved_probe
    if failure == "revision":
        snapshot.revision = 2
    elif failure == "disabled":
        settings.AMBIBOX_INGRESS_ENABLED = False
    elif failure == "host":
        settings.AMBIBOX_ALLOWED_HOST_SUFFIXES = []
    elif failure == "stale":
        snapshot.ingress["checked_at"] = (
            datetime.now(UTC) - timedelta(seconds=30)
        ).isoformat()
    elif failure == "applying":
        snapshot.ingress["status"] = "applying"
    else:
        snapshot.catalog.sources[0].forward_port = None
    with pytest.raises(HTTPException):
        await collection.probe_broker(
            snapshot.catalog.sources[0].id,
            SourceProbeRequest(expected_revision=1),
            User(role=RoleEnum.admin),
            session,
        )
    probe.assert_not_called()


@pytest.mark.asyncio
async def test_probe_api_rejects_catalog_changes_during_observation(saved_probe):
    snapshot, _, probe, session = saved_probe
    session.scalar.return_value = 2
    with pytest.raises(HTTPException) as changed:
        await collection.probe_broker(
            snapshot.catalog.sources[0].id,
            SourceProbeRequest(expected_revision=1),
            User(role=RoleEnum.admin),
            session,
        )
    assert changed.value.status_code == 409
    probe.assert_called_once()


@pytest.mark.asyncio
async def test_probe_api_requires_an_administrator_before_connecting(saved_probe):
    snapshot, _, probe, _ = saved_probe
    app = FastAPI()
    app.include_router(collection.router)
    app.dependency_overrides[collection.current_member] = lambda: User(
        role=RoleEnum.user
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/collection/sources/{snapshot.catalog.sources[0].id}/probe",
            json={"expected_revision": 1},
        )
    assert response.status_code == 403
    probe.assert_not_called()
