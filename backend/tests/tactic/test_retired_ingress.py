"""The cutover removes only generated routes and completes before ingestion."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_tactic_middleware.config.collection import AmbiboxSettings
from off_key_tactic_middleware.services.catalogue import retired_ingress


@pytest.mark.asyncio
async def test_retirement_visits_all_rule_pages_and_leaves_other_resources(monkeypatch):
    responses = {
        "rules?page=1&limit=100": {
            "data": [{"id": "operator-rule"}],
            "meta": {"hasnext": True},
        },
        "rules?page=2&limit=100": {
            "data": [{"id": "offkey_ambibox_fixture"}],
            "meta": {"hasnext": False},
        },
        "sources": [{"name": "offkey_ambibox_fixture"}, {"name": "operator-source"}],
        "connectors": [
            {"name": "offkey_ambibox_fixture"},
            {"name": "operator-connector"},
        ],
    }
    emqx = MagicMock()
    emqx.request = AsyncMock(
        side_effect=lambda method, path: (
            responses.get(path) if method == "GET" else None
        )
    )
    gost = MagicMock()
    gost.request = AsyncMock(
        return_value={
            "services": [{"name": "offkey_ambibox_fixture"}, {"name": "operator-proxy"}]
        }
    )
    monkeypatch.setattr(
        retired_ingress,
        "get_ambibox_settings",
        lambda: AmbiboxSettings(
            AMBIBOX_EMQX_API_KEY="test-key", AMBIBOX_GOST_PASSWORD="test-password"
        ),
    )
    monkeypatch.setattr(
        retired_ingress,
        "ManagementApi",
        lambda url, *_: emqx if "emqx" in url else gost,
    )
    await retired_ingress.retire_v1_ingress()
    assert [
        call.args for call in emqx.request.await_args_list if call.args[0] == "DELETE"
    ] == [
        ("DELETE", "rules/offkey_ambibox_fixture"),
        ("DELETE", "sources/mqtt%3Aoffkey_ambibox_fixture"),
        ("DELETE", "connectors/mqtt%3Aoffkey_ambibox_fixture"),
    ]
    assert gost.request.await_args_list[-1].args == (
        "DELETE",
        "config/services/offkey_ambibox_fixture",
    )
    assert all(
        call.args[0] in {"GET", "DELETE"} for call in emqx.request.await_args_list
    )
    responses.update(
        {
            "rules?page=1&limit=100": {"data": [], "meta": {"hasnext": False}},
            "sources": [],
            "connectors": [],
        }
    )
    emqx.request.reset_mock()
    gost.request.reset_mock()
    gost.request.return_value = {"services": [{"name": "operator-proxy"}]}
    await retired_ingress.retire_v1_ingress()
    assert all(call.args[0] == "GET" for call in emqx.request.await_args_list)
    gost.request.assert_awaited_once_with("GET", "config")


@pytest.mark.asyncio
async def test_retirement_failure_is_retried_before_new_ingress_can_start(monkeypatch):
    emqx = MagicMock()
    emqx.request = AsyncMock(side_effect=retired_ingress.IngressError("unavailable"))
    monkeypatch.setattr(
        retired_ingress,
        "get_ambibox_settings",
        lambda: AmbiboxSettings(AMBIBOX_EMQX_API_KEY="test-key"),
    )
    monkeypatch.setattr(retired_ingress, "ManagementApi", lambda *_: emqx)
    with pytest.raises(retired_ingress.IngressError):
        await retired_ingress.retire_v1_ingress()
    emqx.request.assert_awaited_once_with("GET", "rules?page=1&limit=100")


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{}, {"services": None}, {"services": []}])
async def test_empty_forwarder_configuration_does_not_block_ingress(
    monkeypatch, config
):
    emqx = MagicMock()
    emqx.request = AsyncMock(
        side_effect=lambda _, path: (
            {"data": [], "meta": {"hasnext": False}}
            if path.startswith("rules?")
            else []
        )
    )
    gost = MagicMock()
    gost.request = AsyncMock(return_value=config)
    monkeypatch.setattr(
        retired_ingress,
        "get_ambibox_settings",
        lambda: AmbiboxSettings(
            AMBIBOX_EMQX_API_KEY="test-key", AMBIBOX_GOST_PASSWORD="test-password"
        ),
    )
    monkeypatch.setattr(
        retired_ingress,
        "ManagementApi",
        lambda url, *_: emqx if "emqx" in url else gost,
    )
    await retired_ingress.retire_v1_ingress()
    gost.request.assert_awaited_once_with("GET", "config")


@pytest.mark.asyncio
async def test_no_management_access_makes_no_external_request(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr(
        retired_ingress,
        "get_ambibox_settings",
        lambda: AmbiboxSettings(AMBIBOX_EMQX_API_KEY=""),
    )
    monkeypatch.setattr(retired_ingress, "ManagementApi", factory)
    await retired_ingress.retire_v1_ingress()
    factory.assert_not_called()
