"""Pure conversion of MQTT messages into telemetry records."""

from datetime import UTC, datetime

from off_key_core.utils.mqtt_topics import TopicMetadataExtractor
from off_key_core.utils.string import string_to_float

from .client.models import MQTTMessage
from .telemetry_models import ParseFailure, ParseResult, ParseSuccess, TelemetryRecord


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)

    timestamp = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if timestamp.tzinfo:
        return timestamp.astimezone(UTC)
    return timestamp.replace(tzinfo=UTC)


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

        timestamp_value = payload.get("timestamp")
        try:
            timestamp = (
                _parse_timestamp(timestamp_value)
                if timestamp_value is not None
                else datetime.now(UTC)
            )
        except (ValueError, TypeError, OSError) as error:
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

        return ParseSuccess(
            record=TelemetryRecord(
                charger_id=charger_id,
                timestamp=timestamp,
                value=string_to_float(payload.get("value")),
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
