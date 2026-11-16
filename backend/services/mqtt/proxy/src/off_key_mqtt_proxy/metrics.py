"""Collection counters for Prometheus, read from the proxy's own state on scrape."""

from collections.abc import Iterator

from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.registry import Collector

from .proxy import MQTTProxyService

_BUFFER_COUNTERS = {
    "received": "Ingress envelopes received from the internal broker.",
    "accepted": "Readings admitted by the collection policy.",
    "invalid": "Envelopes or payloads that could not be decoded.",
    "overload_dropped": "Readings dropped because the admission queue was full.",
}


class CollectionCollector(Collector):
    """Expose collection progress without changing how the proxy counts."""

    def __init__(self, service: MQTTProxyService):
        self.service = service

    def collect(self) -> Iterator[CounterMetricFamily | GaugeMetricFamily]:
        buffer = self.service.buffer.metrics()
        writer = self.service.database_writer
        for key, text in _BUFFER_COUNTERS.items():
            yield CounterMetricFamily(
                f"offkey_collection_{key}", text, value=buffer.get(key, 0)
            )
        yield CounterMetricFamily(
            "offkey_collection_written_records",
            "Readings committed to the telemetry log.",
            value=writer.total_records_written,
        )
        yield CounterMetricFamily(
            "offkey_collection_write_batches",
            "Telemetry write batches processed.",
            value=writer.total_batches_processed,
        )
        yield CounterMetricFamily(
            "offkey_collection_failed_write_batches",
            "Telemetry write batches that failed.",
            value=writer.total_batches_failed,
        )
        gauges = {
            "offkey_collection_database_queue": (
                "Readings waiting for the database writer.",
                writer.queued_records,
            ),
            "offkey_collection_database_capacity": (
                "Readings the database writer holds before applying backpressure.",
                writer.queue_capacity,
            ),
            "offkey_collection_database_retrying": (
                "1 while a write batch is being retried.",
                int(writer.is_retrying),
            ),
            "offkey_collection_original_queue": (
                "Readings queued at original rate.",
                buffer.get("original_queue", 0),
            ),
            "offkey_collection_broker_connected": (
                "1 while the proxy is connected to the internal broker.",
                int(self.service.mqtt_client.is_connected),
            ),
            "offkey_collection_revision": (
                "Collection revision the proxy has applied; -1 before the first.",
                self.service.revision,
            ),
        }
        for name, (text, value) in gauges.items():
            yield GaugeMetricFamily(name, text, value=value)
        last = writer.last_successful_write_at
        if last is not None:
            yield GaugeMetricFamily(
                "offkey_collection_last_write_timestamp_seconds",
                "Time of the last committed telemetry batch.",
                value=last.timestamp(),
            )
