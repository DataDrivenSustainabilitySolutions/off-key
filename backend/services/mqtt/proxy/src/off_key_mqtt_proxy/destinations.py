"""Destination adapters used by the MQTT message router."""

import time
from abc import ABC, abstractmethod
from typing import Any, Protocol

from off_key_core.config.logs import logger
from off_key_core.utils.enum import HealthStatus

from .client.models import MQTTMessage
from .routing_models import DestinationHealthStatus, DestinationMetrics


class TelemetryWriter(Protocol):
    async def write_telemetry_message(self, message: MQTTMessage) -> None: ...


class MessagePublisher(Protocol):
    async def publish(
        self,
        topic: str,
        payload: dict[str, Any],
        qos: int = 0,
        retain: bool = False,
    ) -> bool: ...


class MessageDestination(ABC):
    """A measured destination for routed MQTT messages."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.enabled = True
        self.message_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.total_processing_time = 0.0
        self._log_context = {
            "component": "message_router",
            "destination": name,
            "service": "mqtt_proxy",
        }

    @abstractmethod
    async def process_message(self, message: MQTTMessage) -> bool:
        """Process one message and report whether it succeeded."""

    def get_metrics(self) -> DestinationMetrics:
        success_rate = 0.0
        average_processing_time = 0.0
        if self.message_count:
            success_rate = (self.success_count / self.message_count) * 100
            average_processing_time = self.total_processing_time / self.message_count

        return DestinationMetrics(
            name=self.name,
            enabled=self.enabled,
            message_count=self.message_count,
            success_count=self.success_count,
            failure_count=self.failure_count,
            success_rate=round(success_rate, 2),
            average_processing_time=round(average_processing_time, 3),
        )

    def get_health_status(self) -> DestinationHealthStatus:
        metrics = self.get_metrics()
        if not self.enabled:
            status = HealthStatus.DISABLED
        elif not metrics.message_count:
            status = HealthStatus.HEALTHY
        elif metrics.success_rate < 95:
            status = HealthStatus.UNHEALTHY
        elif metrics.success_rate < 98:
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.HEALTHY

        return DestinationHealthStatus(
            destination=self.name,
            status=status,
            metrics=metrics,
        )


class DatabaseDestination(MessageDestination):
    def __init__(self, database_writer: TelemetryWriter) -> None:
        super().__init__("database")
        self.database_writer = database_writer

    async def process_message(self, message: MQTTMessage) -> bool:
        started_at = time.monotonic()
        try:
            await self.database_writer.write_telemetry_message(message)
        except Exception as error:
            self.message_count += 1
            self.failure_count += 1
            logger.error(
                "event=router.destination_failed destination=database "
                "topic=%s error=%s",
                message.topic,
                error,
                extra={
                    **self._log_context,
                    "topic": message.topic,
                    "error": str(error),
                },
                exc_info=True,
            )
            return False

        processing_time = time.monotonic() - started_at
        self.message_count += 1
        self.success_count += 1
        self.total_processing_time += processing_time
        logger.debug(
            "event=router.destination_processed destination=database "
            "topic=%s processing_time_s=%.3f",
            message.topic,
            processing_time,
            extra={
                **self._log_context,
                "topic": message.topic,
                "processing_time": processing_time,
            },
        )
        return True


class BridgeDestination(MessageDestination):
    def __init__(
        self,
        target_client: MessagePublisher,
        topic_mapping: dict[str, str] | None = None,
    ) -> None:
        super().__init__("mqtt_bridge")
        self.target_client = target_client
        self.topic_mapping = topic_mapping or {}

    async def process_message(self, message: MQTTMessage) -> bool:
        started_at = time.monotonic()
        target_topic = self.topic_mapping.get(message.topic, message.topic)
        try:
            success = await self.target_client.publish(
                target_topic,
                message.payload,
                qos=0,
                retain=False,
            )
        except Exception as error:
            self.message_count += 1
            self.failure_count += 1
            logger.error(
                "event=router.destination_failed destination=mqtt_bridge "
                "source_topic=%s target_topic=%s error=%s",
                message.topic,
                target_topic,
                error,
                extra={
                    **self._log_context,
                    "source_topic": message.topic,
                    "target_topic": target_topic,
                    "error": str(error),
                },
                exc_info=True,
            )
            return False

        processing_time = time.monotonic() - started_at
        self.message_count += 1
        self.total_processing_time += processing_time
        if success:
            self.success_count += 1
            logger.debug(
                "event=router.destination_processed destination=mqtt_bridge "
                "source_topic=%s target_topic=%s processing_time_s=%.3f",
                message.topic,
                target_topic,
                processing_time,
                extra={
                    **self._log_context,
                    "source_topic": message.topic,
                    "target_topic": target_topic,
                    "processing_time": processing_time,
                },
            )
            return True

        self.failure_count += 1
        logger.error(
            "event=router.destination_failed destination=mqtt_bridge "
            "source_topic=%s target_topic=%s error=publish_failed",
            message.topic,
            target_topic,
            extra={
                **self._log_context,
                "source_topic": message.topic,
                "target_topic": target_topic,
                "error": "publish_failed",
            },
        )
        return False
