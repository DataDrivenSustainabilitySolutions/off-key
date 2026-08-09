"""Pure conversion of MQTT messages into telemetry records."""

from datetime import UTC, datetime
from math import isfinite

from off_key_core.utils.mqtt_topics import TopicMetadataExtractor
from off_key_core.utils.string import string_to_float
from off_key_core.utils.timestamps import parse_utc_timestamp

from .client.models import MQTTMessage
from .telemetry_models import ParseFailure, ParseResult, ParseSuccess, TelemetryRecord


def parse_telemetry_message(
    message: MQTTMessage,
    topic_extractor: TopicMetadataExtractor,
) -> ParseResult:
    """Parse one MQTT message without I/O or shared-state mutation."""
    try:
        payload = message.payload
        metadata = topic_extractor.extract(message.topic, payload)
        if metadata is None:
            return ParseFailure(
                reason="Topic metadata extraction failed",
                is_error=False,
                log_message=f"Unable to extract metadata from topic: {message.topic}",
                context={"topic": message.topic},
            )

        charger_id = metadata.charger_id
        telemetry_type = metadata.telemetry_type
        if not telemetry_type:
            return ParseFailure(
                reason="Missing telemetry type",
                is_error=False,
                log_message=(
                    f"Missing telemetry type after extraction: {message.topic}"
                ),
                context={"charger_id": charger_id, "topic": message.topic},
            )

        has_timestamp = "timestamp" in payload
        timestamp_value = payload.get("timestamp")
        try:
            timestamp = (
                parse_utc_timestamp(timestamp_value)
                if has_timestamp
                else datetime.now(UTC)
            )
        except (ValueError, TypeError, OSError, OverflowError) as error:
            timestamp_context = str(timestamp_value)
            return ParseFailure(
                reason="Invalid timestamp format",
                is_error=False,
                log_message=f"Invalid timestamp format: {timestamp_context}",
                context={
                    "charger_id": charger_id,
                    "timestamp": timestamp_context,
                    "error": str(error),
                },
            )

        raw_value = payload.get("value")
        value = None if isinstance(raw_value, bool) else string_to_float(raw_value)
        if value is None or not isfinite(value):
            return ParseFailure(
                reason="Invalid telemetry value",
                is_error=False,
                log_message=f"Invalid telemetry value for topic: {message.topic}",
                context={
                    "charger_id": charger_id,
                    "telemetry_type": telemetry_type,
                    "topic": message.topic,
                },
            )

        return ParseSuccess(
            record=TelemetryRecord(
                charger_id=charger_id,
                timestamp=timestamp,
                value=value,
                telemetry_type=telemetry_type,
                created=datetime.now(UTC),
            )
        )
    except Exception as error:
        return ParseFailure(
            reason="Unexpected parsing error",
            is_error=True,
            log_message=f"Error parsing telemetry message: {error}",
            context={
                "topic": message.topic,
                "payload": message.payload,
                "error": str(error),
            },
        )
