import ssl
from aiomqtt import Client as MQTTClient
from off_key_core.db.base import AsyncSessionLocal
from off_key_core.clients.provider import get_charger_api_client

from .config import mqtt_settings
from off_key_mqtt_bridge.chargers.discovery import ChargerDiscoveryService
from off_key_mqtt_bridge.chargers.sync import ChargersSyncService

import logging
from off_key_core.db.base import async_engine
from off_key_core.db.models import Base


# Helper functions for startup tasks
async def _initialize_database():
    """Creates all database tables."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logging.info("Database tables created successfully")


async def forward_messages(external: MQTTClient, internal: MQTTClient):
    async for msg in external.messages:
        await internal.publish(str(msg.topic), msg.payload, qos=1)


async def main():
    # Setup new DB
    await _initialize_database()

    # Setup DB and API clients
    async_session = AsyncSessionLocal()
    api_client = get_charger_api_client()

    # Sync chargers info
    await ChargersSyncService(async_session, api_client).sync_chargers()

    # Get updated chargers:
    discovery = ChargerDiscoveryService(mqtt_settings, async_session, api_client)
    chargers = await discovery.discover_chargers()
    await async_session.close()

    # Define SSL context
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # For WebSocket connections

    # Define MQTT Clients settings
    ext_client_config = dict(
        hostname=mqtt_settings.MQTT_EXTERNAL_HOST,
        port=mqtt_settings.MQTT_EXTERNAL_PORT,
        identifier=mqtt_settings.MQTT_EXTERNAL_CLIENT_ID,
        transport="websockets",
        username=mqtt_settings.MQTT_EXTERNAL_USERNAME,
        password=mqtt_settings.MQTT_EXTERNAL_APIKEY.get_secret_value(),
        keepalive=15,
        tls_context=context,
    )

    int_client_config = dict(
        hostname=mqtt_settings.MQTT_INTERNAL_HOST,
        port=mqtt_settings.MQTT_INTERNAL_PORT,
        keepalive=60,
        clean_session=True,
    )
    # Setup MQTT Clients
    ext_client = MQTTClient(**ext_client_config)
    int_client = MQTTClient(**int_client_config)

    async with ext_client as ext_client_session:
        # Subscribe to all charger topics
        for charger_info in chargers:
            await discovery.subscribe_to_charger_topics(
                ext_client_session, charger_info
            )
        # Forward messages to internal broker
        async with int_client as int_client_session:
            await forward_messages(ext_client_session, int_client_session)
