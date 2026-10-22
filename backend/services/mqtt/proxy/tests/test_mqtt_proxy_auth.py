"""Username/API-key credentials the proxy presents to the MQTT broker."""

import pytest
from off_key_mqtt_proxy.auth import (
    ApiKeyAuthError,
    ApiKeyAuthHandler,
    ApiKeyCredentials,
)


async def test_handler_provides_broker_credentials_for_its_lifetime():
    async with ApiKeyAuthHandler("ingest", "key-123") as handler:
        assert await handler.authenticate() == ApiKeyCredentials("ingest", "key-123")
        assert await handler.get_mqtt_credentials() == ("ingest", "key-123")


@pytest.mark.parametrize(("username", "api_key"), [("", "key-123"), ("ingest", "")])
def test_handler_requires_both_username_and_key(username, api_key):
    with pytest.raises(ApiKeyAuthError, match="required"):
        ApiKeyAuthHandler(username, api_key)


async def test_cleared_credentials_are_never_sent_to_the_broker():
    handler = ApiKeyAuthHandler("ingest", "key-123")
    handler.credentials.api_key = ""

    with pytest.raises(ApiKeyAuthError):
        await handler.authenticate()
    with pytest.raises(ApiKeyAuthError):
        await handler.get_mqtt_credentials()
