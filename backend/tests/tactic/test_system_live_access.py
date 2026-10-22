"""The generic preview reuses explicitly configured provider access privately."""

import json
from unittest.mock import MagicMock

import pytest
from off_key_core.schemas.system import SystemDocument, SystemSnapshot
from off_key_tactic_middleware.config.collection import AmbiboxSettings
from off_key_tactic_middleware.config.system_live import SystemLiveSettings
from off_key_tactic_middleware.services.ambibox_live_access import AmbiboxLiveAccess
from off_key_tactic_middleware.services.system_live import SystemLiveService


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


def provider(**overrides):
    return AmbiboxLiveAccess(
        AmbiboxSettings(
            AMBIBOX_INGRESS_ENABLED=True,
            AMBIBOX_ALLOWED_HOSTS=["vendor-broker"],
            AMBIBOX_ALLOWED_HOST_SUFFIXES=[],
            AMBIBOX_MQTT_USERNAME="operator",
            AMBIBOX_MQTT_PASSWORD="private-password",
            **overrides,
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("require_tls", [True, False])
async def test_preview_reuses_registered_tailnet_and_existing_mqtt_credentials(
    require_tls,
):
    worker_factory = MagicMock()
    service = SystemLiveService(
        SystemLiveSettings(SYSTEM_LIVE_ENABLED=True),
        worker_factory=worker_factory,
        access_resolver=provider(AMBIBOX_MQTT_TLS=require_tls),
    )
    saved = snapshot(host="vendor-broker")
    original = saved.model_dump_json()
    try:
        lease = await service.acquire(saved, 1, 1)
        arguments, options = worker_factory.call_args
        assert options["proxy"].host == "tailscale-ambibox"
        assert options["proxy"].port == 1055
        assert arguments[2].username == "operator"
        assert arguments[2].password.get_secret_value() == "private-password"
        assert arguments[0].host == "vendor-broker"
        assert arguments[0].tls is require_tls
        assert saved.model_dump_json() == original
        assert "private-password" not in json.dumps(lease)
        assert "tailscale-ambibox" not in json.dumps(lease)
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_provider_does_not_approve_other_hosts_or_missing_explicit_credentials():
    for saved in [
        snapshot(host="unapproved"),
        snapshot(host="vendor-broker", credential_ref="unconfigured"),
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


@pytest.mark.parametrize(
    "endpoint",
    ["proxy:invalid", "user:password@proxy:1055", "proxy:1055/path", "proxy:70000"],
)
def test_invalid_provider_proxy_fails_closed(endpoint):
    assert (
        provider(AMBIBOX_SOCKS_SERVER=endpoint)(
            snapshot(host="vendor-broker").document.connections[0]
        )
        is None
    )


def test_disabled_provider_does_not_grant_access():
    access = AmbiboxLiveAccess(AmbiboxSettings(AMBIBOX_INGRESS_ENABLED=False))
    assert (
        access(snapshot(host="broker.example.ts.net").document.connections[0]) is None
    )


@pytest.mark.asyncio
async def test_simulated_origin_is_explicit_in_telemetry():
    service = SystemLiveService(SystemLiveSettings(SYSTEM_LIVE_DATA_SOURCE="simulated"))
    assert service.snapshot(0)["data_source"] == "simulated"
