from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from off_key_core.utils.mqtt_topics import TopicMetadataExtractor
from off_key_mqtt_proxy.client.models import MQTTMessage
from off_key_mqtt_proxy.telemetry import DatabaseWriter, ParseSuccess


def _writer() -> DatabaseWriter:
    config = MagicMock()
    config.batch_size = 100
    config.batch_timeout = 5.0
    config.graceful_shutdown_timeout = 5.0
    return DatabaseWriter(
        config=config,
        session_factory=MagicMock(),
        topic_extractor=TopicMetadataExtractor(),
    )


@pytest.mark.asyncio
async def test_parse_telemetry_message_converts_offset_timestamp_to_utc():
    writer = _writer()
    message = MQTTMessage(
        topic="charger/charger-1/live-telemetry/sine",
        payload={"timestamp": "2024-01-01T12:00:00+02:00", "value": "2.5"},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )

    result = await writer._parse_telemetry_message(message)

    assert isinstance(result, ParseSuccess)
    assert result.record.timestamp == datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert result.record.created.tzinfo is not None


@pytest.mark.asyncio
async def test_parse_telemetry_message_treats_naive_timestamp_as_utc():
    writer = _writer()
    message = MQTTMessage(
        topic="charger/charger-1/live-telemetry/sine",
        payload={"timestamp": "2024-01-01T12:00:00", "value": "2.5"},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )

    result = await writer._parse_telemetry_message(message)

    assert isinstance(result, ParseSuccess)
    assert result.record.timestamp == datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
