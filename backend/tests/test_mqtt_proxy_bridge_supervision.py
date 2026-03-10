import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from off_key_mqtt_proxy.proxy import MQTTProxyService


def _build_proxy_config() -> SimpleNamespace:
    return SimpleNamespace(
        mqtt_username="proxy-user",
        mqtt_api_key="proxy-key-123456",
        enable_bridge=True,
        bridge_broker_host="emqx-main",
        bridge_broker_port=1883,
        bridge_use_tls=False,
        bridge_client_id_prefix="offkey-bridge",
        bridge_use_auth=False,
        bridge_username="",
        bridge_api_key="",
        reconnect_delay=1,
        max_reconnect_attempts=10,
        batch_size=100,
        batch_timeout=5.0,
        subscription_qos=1,
        health_check_interval=35,
        health_log_reminder_interval=10,
        connection_timeout=10.0,
        max_message_queue_size=10000,
        worker_threads=4,
        shutdown_timeout=1.0,
        graceful_shutdown_timeout=5.0,
        health_monitor_interval=0.01,
        get_jittered_backoff_delay=lambda _: 0.01,
    )


def _build_service(config: SimpleNamespace) -> MQTTProxyService:
    with patch(
        "off_key_mqtt_proxy.proxy.get_mqtt_settings",
        return_value=SimpleNamespace(config=config),
    ):
        return MQTTProxyService(api_client=MagicMock())


@pytest.mark.asyncio
async def test_start_survives_initial_bridge_failure():
    config = _build_proxy_config()
    service = _build_service(config)

    auth_handler = MagicMock()
    auth_handler.authenticate = AsyncMock()
    auth_handler.stop = AsyncMock()

    mqtt_client = MagicMock()
    mqtt_client.connect = AsyncMock(return_value=True)
    mqtt_client.set_message_handler = MagicMock()
    mqtt_client.stop = AsyncMock()
    mqtt_client.state = SimpleNamespace(value="connected")

    charger_discovery = MagicMock()
    charger_discovery.discover_chargers = AsyncMock(return_value=[])
    charger_discovery.subscribe_to_charger_topics = AsyncMock()
    charger_discovery.get_all_topics = MagicMock(return_value=[])
    charger_discovery.stop = AsyncMock()

    database_writer = MagicMock()
    database_writer.start = AsyncMock()
    database_writer.stop = AsyncMock()
    database_writer.get_health_status = MagicMock(return_value={"status": "healthy"})
    database_writer.get_performance_metrics = MagicMock(return_value={})

    message_router = MagicMock()
    message_router.start = AsyncMock()
    message_router.stop = AsyncMock()
    message_router.add_destination = MagicMock()
    message_router.get_health_status = MagicMock(return_value={"status": "healthy"})
    message_router.get_performance_metrics = MagicMock(return_value={})

    with (
        patch(
            "off_key_mqtt_proxy.proxy.get_async_session_local",
            return_value=MagicMock(),
        ),
        patch("off_key_mqtt_proxy.proxy.ApiKeyAuthHandler", return_value=auth_handler),
        patch("off_key_mqtt_proxy.proxy.MQTTClient", return_value=mqtt_client),
        patch(
            "off_key_mqtt_proxy.proxy.ChargerDiscoveryService",
            return_value=charger_discovery,
        ),
        patch("off_key_mqtt_proxy.proxy.DatabaseWriter", return_value=database_writer),
        patch("off_key_mqtt_proxy.proxy.MessageRouter", return_value=message_router),
        patch.object(
            service,
            "_connect_bridge_once",
            new=AsyncMock(return_value=False),
        ) as connect_bridge_once_mock,
        patch.object(
            service, "_start_bridge_supervisor", new=MagicMock()
        ) as start_bridge_supervisor_mock,
    ):
        await service.start()

    assert service.is_running is True
    connect_bridge_once_mock.assert_awaited_once()
    start_bridge_supervisor_mock.assert_called_once()


@pytest.mark.asyncio
async def test_bridge_supervisor_retries_until_connected():
    config = _build_proxy_config()
    service = _build_service(config)
    service.message_router = MagicMock()
    service.bridge_destination = MagicMock(enabled=False)

    attempts = {"count": 0}

    async def _fake_connect_once():
        attempts["count"] += 1
        if attempts["count"] < 3:
            return False

        service.bridge_client = MagicMock(is_connected=True)
        service.bridge_destination.enabled = True
        service.bridge_connected_event.set()
        return True

    with patch.object(
        service,
        "_connect_bridge_once",
        new=AsyncMock(side_effect=_fake_connect_once),
    ):
        supervisor_task = asyncio.create_task(service._bridge_supervisor_loop())
        await asyncio.wait_for(service.bridge_connected_event.wait(), timeout=0.5)
        service.shutdown_event.set()
        await supervisor_task

    assert attempts["count"] >= 3
    assert service.bridge_destination.enabled is False


@pytest.mark.asyncio
async def test_readiness_requires_bridge_when_enabled():
    config = _build_proxy_config()
    service = _build_service(config)

    service.is_running = True
    service.mqtt_client = MagicMock(is_connected=True)
    service.bridge_destination = MagicMock(enabled=True)
    service.bridge_connected_event.set()
    service.bridge_supervisor_task = asyncio.create_task(asyncio.sleep(0.1))

    try:
        assert service.is_bridge_ready() is True
        readiness = service.get_readiness_status()
        assert readiness["ready"] is True
        assert readiness["bridge_required"] is True
    finally:
        service.bridge_supervisor_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await service.bridge_supervisor_task


@pytest.mark.asyncio
async def test_readiness_without_bridge_only_requires_primary_connection():
    config = _build_proxy_config()
    config.enable_bridge = False
    service = _build_service(config)

    service.is_running = True
    service.mqtt_client = MagicMock(is_connected=True)

    readiness = service.get_readiness_status()
    assert service.is_bridge_ready() is True
    assert readiness["ready"] is True
    assert readiness["bridge_required"] is False
