"""
Optimized Database Writer for MQTT Telemetry Data

High-performance, batched database writer for real-time telemetry data with
intelligent logging, error handling, and performance optimization.
"""

import asyncio
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import update

from ...core.logs import logger, log_performance
from ...db.models import Telemetry, Charger
from ...utils.string import clean_string, string_to_float
from .config import MQTTConfig
from .mqtt_client import MQTTMessage


class WriteStatus(Enum):
    """Database write status"""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class TelemetryRecord:
    """Telemetry record for database insertion"""

    charger_id: str
    timestamp: datetime
    value: Optional[float]
    telemetry_type: str
    created: datetime

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database insertion"""
        return {
            "charger_id": self.charger_id,
            "timestamp": self.timestamp,
            "value": self.value,
            "type": self.telemetry_type,
            "created": self.created,
        }


@dataclass
class WriteBatch:
    """Batch of telemetry records for database insertion"""

    records: List[TelemetryRecord] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    status: WriteStatus = WriteStatus.PENDING
    retry_count: int = 0
    last_error: Optional[str] = None

    def add_record(self, record: TelemetryRecord):
        """Add record to batch"""
        self.records.append(record)

    def size(self) -> int:
        """Get batch size"""
        return len(self.records)

    def get_charger_ids(self) -> set:
        """Get unique charger IDs in batch"""
        return {record.charger_id for record in self.records}

    def get_age_seconds(self) -> float:
        """Get batch age in seconds"""
        return (datetime.now() - self.created_at).total_seconds()


class DatabaseWriterError(Exception):
    """Database writer error"""

    pass


class DatabaseWriter:
    """
    High-performance database writer for MQTT telemetry data

    Features:
    - Batched writes with configurable size and timeout
    - Automatic retry with exponential backoff
    - Dead letter queue for failed records
    - Performance monitoring and metrics
    - Intelligent logging with context
    - Duplicate detection and handling
    - Connection health monitoring
    """

    def __init__(self, config: MQTTConfig, db_session: AsyncSession):
        self.config = config
        self.db_session = db_session

        # Batching configuration
        self.batch_size = config.batch_size
        self.batch_timeout = config.batch_timeout
        self.max_retries = 3
        self.retry_delay = 1.0

        # Write queues
        self.pending_batch = WriteBatch()
        self.processing_batches: Dict[str, WriteBatch] = {}
        self.failed_batches: List[WriteBatch] = []

        # Performance metrics
        self.total_records_received = 0
        self.total_records_written = 0
        self.total_records_failed = 0
        self.total_batches_processed = 0
        self.total_batches_failed = 0
        self.write_latency_sum = 0.0
        self.write_latency_count = 0

        # Charger status tracking
        self.charger_last_seen: Dict[str, datetime] = {}
        self.charger_message_counts: Dict[str, int] = defaultdict(int)

        # Background tasks
        self._writer_task: Optional[asyncio.Task] = None
        self._health_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # Logging context
        self._log_context = {"component": "database_writer", "service": "mqtt_proxy"}

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def start(self):
        """Start the database writer"""
        logger.info("Starting database writer", extra=self._log_context)

        # Start background tasks
        self._writer_task = asyncio.create_task(self._writer_loop())
        self._health_task = asyncio.create_task(self._health_monitor_loop())

        logger.info(
            "Database writer started successfully",
            extra={
                **self._log_context,
                "batch_size": self.batch_size,
                "batch_timeout": self.batch_timeout,
                "max_retries": self.max_retries,
            },
        )

    async def stop(self):
        """Stop the database writer"""
        logger.info("Stopping database writer", extra=self._log_context)

        # Signal shutdown
        self._shutdown_event.set()

        # Cancel background tasks
        if self._writer_task and not self._writer_task.done():
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass

        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        # Process remaining batches
        if self.pending_batch.size() > 0:
            logger.info(
                f"Processing {self.pending_batch.size()} "
                f"remaining records during shutdown",
                extra={**self._log_context, "records_count": self.pending_batch.size()},
            )
            await self._process_batch(self.pending_batch)

        logger.info("Database writer stopped", extra=self._log_context)

    async def write_telemetry_message(self, message: MQTTMessage):
        """
        Write MQTT telemetry message to database

        Args:
            message: MQTT message containing telemetry data
        """
        try:
            # Parse message
            record = await self._parse_telemetry_message(message)
            if not record:
                return

            # Add to batch
            self.pending_batch.add_record(record)
            self.total_records_received += 1

            # Update charger tracking
            self.charger_last_seen[record.charger_id] = record.timestamp
            self.charger_message_counts[record.charger_id] += 1

            # Log high-frequency messages intelligently
            if self.total_records_received % 100 == 0:
                logger.debug(
                    f"Queued telemetry record (total: {self.total_records_received})",
                    extra={
                        **self._log_context,
                        "charger_id": record.charger_id,
                        "telemetry_type": record.telemetry_type,
                        "batch_size": self.pending_batch.size(),
                        "total_received": self.total_records_received,
                    },
                )

            # Check if batch is ready for processing
            if (
                self.pending_batch.size() >= self.batch_size
                or self.pending_batch.get_age_seconds() >= self.batch_timeout
            ):
                await self._trigger_batch_processing()

        except Exception as e:
            logger.error(
                f"Error processing telemetry message: {e}",
                extra={**self._log_context, "topic": message.topic, "error": str(e)},
                exc_info=True,
            )

    async def _parse_telemetry_message(
        self, message: MQTTMessage
    ) -> Optional[TelemetryRecord]:
        """Parse MQTT message into telemetry record"""
        try:
            # Extract charger ID from topic
            # Topic format: charger/{charger_id}/live-telemetry/{hierarchy}
            topic_parts = message.topic.split("/")
            if len(topic_parts) < 4 or topic_parts[0] != "charger":
                logger.warning(
                    f"Invalid topic format: {message.topic}",
                    extra={**self._log_context, "topic": message.topic},
                )
                return None

            charger_id = topic_parts[1]
            hierarchy = "/".join(topic_parts[3:])  # Reconstruct hierarchy

            # Clean hierarchy for database storage
            telemetry_type = clean_string(hierarchy)
            if not telemetry_type:
                logger.warning(
                    f"Invalid hierarchy after cleaning: {hierarchy}",
                    extra={
                        **self._log_context,
                        "charger_id": charger_id,
                        "hierarchy": hierarchy,
                    },
                )
                return None

            # Extract value and timestamp from payload
            payload = message.payload

            # Parse timestamp
            timestamp_str = payload.get("timestamp")
            if timestamp_str:
                try:
                    if timestamp_str.endswith("Z"):
                        timestamp = datetime.fromisoformat(
                            timestamp_str.replace("Z", "+00:00")
                        )
                    else:
                        timestamp = datetime.fromisoformat(timestamp_str)

                    # Convert to naive datetime for database storage
                    if timestamp.tzinfo:
                        timestamp = timestamp.replace(tzinfo=None)
                except (ValueError, TypeError) as e:
                    logger.warning(
                        f"Invalid timestamp format: {timestamp_str}",
                        extra={
                            **self._log_context,
                            "charger_id": charger_id,
                            "timestamp": timestamp_str,
                            "error": str(e),
                        },
                    )
                    timestamp = datetime.now()
            else:
                timestamp = datetime.now()

            # Parse value
            value = string_to_float(payload.get("value"))

            # Create record
            record = TelemetryRecord(
                charger_id=charger_id,
                timestamp=timestamp,
                value=value,
                telemetry_type=telemetry_type,
                created=datetime.now(),
            )

            return record

        except Exception as e:
            logger.error(
                f"Error parsing telemetry message: {e}",
                extra={
                    **self._log_context,
                    "topic": message.topic,
                    "payload": message.payload,
                    "error": str(e),
                },
                exc_info=True,
            )
            return None

    async def _trigger_batch_processing(self):
        """Trigger processing of current batch"""
        if self.pending_batch.size() == 0:
            return

        # Move current batch to processing
        batch_id = f"batch_{int(time.time() * 1000)}"
        self.processing_batches[batch_id] = self.pending_batch
        self.pending_batch = WriteBatch()

        # Process batch in background
        asyncio.create_task(self._process_batch_with_retry(batch_id))

    async def _writer_loop(self):
        """Background loop for batch processing"""
        try:
            while not self._shutdown_event.is_set():
                # Check if batch timeout has been reached
                if (
                    self.pending_batch.size() > 0
                    and self.pending_batch.get_age_seconds() >= self.batch_timeout
                ):

                    logger.debug(
                        f"Batch timeout reached, "
                        f"processing {self.pending_batch.size()} records",
                        extra={
                            **self._log_context,
                            "batch_size": self.pending_batch.size(),
                            "batch_age": self.pending_batch.get_age_seconds(),
                        },
                    )
                    await self._trigger_batch_processing()

                # Sleep for a short interval
                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.info("Writer loop cancelled", extra=self._log_context)
        except Exception as e:
            logger.error(
                f"Unexpected error in writer loop: {e}",
                extra=self._log_context,
                exc_info=True,
            )

    async def _process_batch_with_retry(self, batch_id: str):
        """Process batch with retry logic"""
        batch = self.processing_batches.get(batch_id)
        if not batch:
            return

        max_attempts = self.max_retries + 1

        for attempt in range(max_attempts):
            try:
                batch.status = (
                    WriteStatus.PROCESSING if attempt == 0 else WriteStatus.RETRYING
                )
                batch.retry_count = attempt

                if attempt > 0:
                    delay = self.retry_delay * (2 ** (attempt - 1))
                    logger.info(
                        f"Retrying batch processing "
                        f"(attempt {attempt + 1}/{max_attempts}) in {delay}s",
                        extra={
                            **self._log_context,
                            "batch_id": batch_id,
                            "batch_size": batch.size(),
                            "retry_count": attempt,
                            "delay": delay,
                        },
                    )
                    await asyncio.sleep(delay)

                success = await self._process_batch(batch)

                if success:
                    batch.status = WriteStatus.SUCCESS
                    self.processing_batches.pop(batch_id, None)
                    logger.info(
                        "Batch processed successfully",
                        extra={
                            **self._log_context,
                            "batch_id": batch_id,
                            "batch_size": batch.size(),
                            "attempt": attempt + 1,
                        },
                    )
                    return

            except Exception as e:
                logger.error(
                    f"Error processing batch (attempt {attempt + 1}): {e}",
                    extra={
                        **self._log_context,
                        "batch_id": batch_id,
                        "batch_size": batch.size(),
                        "attempt": attempt + 1,
                        "error": str(e),
                    },
                    exc_info=True,
                )
                batch.last_error = str(e)

        # All attempts failed
        batch.status = WriteStatus.FAILED
        self.failed_batches.append(batch)
        self.processing_batches.pop(batch_id, None)
        self.total_batches_failed += 1

        logger.error(
            f"Batch processing failed after {max_attempts} attempts",
            extra={
                **self._log_context,
                "batch_id": batch_id,
                "batch_size": batch.size(),
                "last_error": batch.last_error,
                "charger_ids": list(batch.get_charger_ids()),
            },
        )

    async def _process_batch(self, batch: WriteBatch) -> bool:
        """Process a batch of telemetry records"""
        if batch.size() == 0:
            return True

        start_time = time.time()

        try:
            # Convert records to database format
            records_data = [record.to_dict() for record in batch.records]

            # Perform bulk insert with conflict handling
            stmt = insert(Telemetry).values(records_data)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["charger_id", "timestamp", "type"]
            )

            result = await self.db_session.execute(stmt)  # noqa
            await self.db_session.commit()

            # Update metrics
            records_written = len(
                records_data
            )  # Approximate, actual may be less due to conflicts
            self.total_records_written += records_written
            self.total_batches_processed += 1

            # Track write latency
            write_latency = time.time() - start_time
            self.write_latency_sum += write_latency
            self.write_latency_count += 1

            # Update charger statuses
            await self._update_charger_statuses(batch.get_charger_ids())

            # Log batch processing with intelligent frequency
            if self.total_batches_processed % 10 == 0 or write_latency > 1.0:
                log_level = "info" if write_latency <= 1.0 else "warning"
                logger.log(
                    logger.INFO if log_level == "info" else logger.WARNING,
                    f"Batch processed: {records_written} "
                    f"records in {write_latency:.3f}s",
                    extra={
                        **self._log_context,
                        "batch_size": records_written,
                        "write_latency": write_latency,
                        "total_batches": self.total_batches_processed,
                        "total_records": self.total_records_written,
                        "avg_latency": self.write_latency_sum
                        / self.write_latency_count,
                        "charger_count": len(batch.get_charger_ids()),
                    },
                )

            # Performance logging
            log_performance(
                "telemetry_batch_write",
                start_time,
                {
                    "batch_size": records_written,
                    "charger_count": len(batch.get_charger_ids()),
                    "component": "database_writer",
                },
            )

            return True

        except IntegrityError as e:
            logger.warning(
                f"Integrity error during batch processing (likely duplicates): {e}",
                extra={
                    **self._log_context,
                    "batch_size": batch.size(),
                    "error": str(e),
                },
            )
            await self.db_session.rollback()
            return True  # Treat as success since it's likely just duplicates

        except SQLAlchemyError as e:
            logger.error(
                f"Database error during batch processing: {e}",
                extra={
                    **self._log_context,
                    "batch_size": batch.size(),
                    "error": str(e),
                },
            )
            await self.db_session.rollback()
            return False

        except Exception as e:
            logger.error(
                f"Unexpected error during batch processing: {e}",
                extra={
                    **self._log_context,
                    "batch_size": batch.size(),
                    "error": str(e),
                },
                exc_info=True,
            )
            await self.db_session.rollback()
            return False

    async def _update_charger_statuses(self, charger_ids: set):
        """Update charger MQTT connection statuses"""
        try:
            now = datetime.now()

            # Update chargers' MQTT status
            for charger_id in charger_ids:
                last_seen = self.charger_last_seen.get(charger_id, now)

                stmt = (
                    update(Charger)
                    .where(Charger.charger_id == charger_id)
                    .values(mqtt_connected=True, mqtt_last_message=last_seen)
                )

                await self.db_session.execute(stmt)

            await self.db_session.commit()

        except Exception as e:
            logger.error(
                f"Error updating charger statuses: {e}",
                extra={
                    **self._log_context,
                    "charger_ids": list(charger_ids),
                    "error": str(e),
                },
            )
            await self.db_session.rollback()

    async def _health_monitor_loop(self):
        """Background health monitoring loop"""
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(30)  # Check every 30 seconds

                # Log health metrics periodically
                metrics = self.get_performance_metrics()
                health = self.get_health_status()

                if health["status"] != "healthy":
                    logger.warning(
                        f"Database writer health check: {health['status']}",
                        extra={
                            **self._log_context,
                            "health_status": health,
                            "performance_metrics": metrics,
                        },
                    )
                elif self.total_batches_processed % 100 == 0:
                    logger.info(
                        f"Database writer health check: {health['status']}",
                        extra={
                            **self._log_context,
                            "health_status": health,
                            "performance_metrics": metrics,
                        },
                    )

        except asyncio.CancelledError:
            logger.info("Health monitor loop cancelled", extra=self._log_context)
        except Exception as e:
            logger.error(
                f"Unexpected error in health monitor loop: {e}",
                extra=self._log_context,
                exc_info=True,
            )

    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get performance metrics"""
        avg_latency = 0
        if self.write_latency_count > 0:
            avg_latency = self.write_latency_sum / self.write_latency_count

        success_rate = 100
        if self.total_batches_processed + self.total_batches_failed > 0:
            success_rate = (
                self.total_batches_processed
                / (self.total_batches_processed + self.total_batches_failed)
            ) * 100

        return {
            "total_records_received": self.total_records_received,
            "total_records_written": self.total_records_written,
            "total_records_failed": self.total_records_failed,
            "total_batches_processed": self.total_batches_processed,
            "total_batches_failed": self.total_batches_failed,
            "batch_success_rate": round(success_rate, 2),
            "average_write_latency": round(avg_latency, 3),
            "pending_batch_size": self.pending_batch.size(),
            "processing_batches_count": len(self.processing_batches),
            "failed_batches_count": len(self.failed_batches),
            "unique_chargers_seen": len(self.charger_last_seen),
            "total_messages_by_charger": dict(self.charger_message_counts),
        }

    def get_health_status(self) -> Dict[str, Any]:
        """Get health status for monitoring"""
        metrics = self.get_performance_metrics()

        # Determine health status
        status = "healthy"

        # Check for high failure rate
        if metrics["batch_success_rate"] < 95:
            status = "unhealthy"
        elif metrics["batch_success_rate"] < 98:
            status = "degraded"

        # Check for high latency
        if metrics["average_write_latency"] > 5.0:
            status = "unhealthy"
        elif metrics["average_write_latency"] > 2.0:
            status = "degraded"

        # Check for too many pending batches
        if metrics["processing_batches_count"] > 10:
            status = "unhealthy"
        elif metrics["processing_batches_count"] > 5:
            status = "degraded"

        return {
            "status": status,
            "records_per_second": self._calculate_records_per_second(),
            "batches_per_minute": self._calculate_batches_per_minute(),
            **metrics,
        }

    def _calculate_records_per_second(self) -> float:
        """Calculate records per second rate"""
        if self.write_latency_count > 0 and self.write_latency_sum > 0:
            return round(self.total_records_written / self.write_latency_sum, 2)
        return 0.0

    def _calculate_batches_per_minute(self) -> float:
        """Calculate batches per minute rate"""
        if self.write_latency_count > 0 and self.write_latency_sum > 0:
            return round(
                (self.total_batches_processed / self.write_latency_sum) * 60, 2
            )
        return 0.0
