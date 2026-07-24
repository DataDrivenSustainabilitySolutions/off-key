"""Telemetry records, batches, and writer health results."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from off_key_core.utils.enum import HealthStatus


@dataclass(frozen=True, slots=True)
class WriterPerformanceMetrics:
    total_records_received: int
    total_records_written: int
    total_records_failed: int
    total_batches_processed: int
    total_batches_failed: int
    batch_success_rate: float
    average_write_latency: float
    pending_batch_size: int
    processing_batches_count: int
    failed_batches_count: int
    unique_chargers_seen: int
    total_messages_by_charger: dict[str, int]


@dataclass(frozen=True, slots=True)
class WriterHealthStatus:
    status: HealthStatus
    records_per_second: float
    batches_per_minute: float
    performance: WriterPerformanceMetrics


class WriteStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass(frozen=True, slots=True)
class TelemetryRecord:
    charger_id: str
    timestamp: datetime
    value: float | None
    telemetry_type: str
    created: datetime
    data_source: str = "mqtt"

    def to_dict(self) -> dict[str, object]:
        return {
            "charger_id": self.charger_id,
            "timestamp": self.timestamp,
            "value": self.value,
            "type": self.telemetry_type,
            "data_source": self.data_source,
            "created": self.created,
        }


@dataclass(frozen=True, slots=True)
class ParseSuccess:
    record: TelemetryRecord


@dataclass(frozen=True, slots=True)
class ParseFailure:
    reason: str
    is_error: bool
    log_message: str
    context: dict[str, object]


ParseResult = ParseSuccess | ParseFailure


@dataclass(slots=True)
class WriteBatch:
    records: list[TelemetryRecord] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: WriteStatus = WriteStatus.PENDING
    retry_count: int = 0
    last_error: str | None = None

    def add_record(self, record: TelemetryRecord) -> None:
        self.records.append(record)

    def size(self) -> int:
        return len(self.records)

    def get_charger_ids(self) -> set[str]:
        return {record.charger_id for record in self.records}

    def get_age_seconds(self) -> float:
        return (datetime.now(UTC) - self.created_at).total_seconds()
