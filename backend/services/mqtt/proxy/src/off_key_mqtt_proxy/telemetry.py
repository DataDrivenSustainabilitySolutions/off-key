"""
Database Writer for MQTT Telemetry Data
"""

import asyncio
import time
from collections import defaultdict
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from off_key_core.config.logs import log_performance, logger
from off_key_core.db.models import Charger, Telemetry
from off_key_core.utils.enum import HealthStatus
from off_key_core.utils.mqtt_topics import TopicMetadataExtractor
from off_key_core.utils.string import string_to_float
from sqlalchemy import case, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .client.models import MQTTMessage
from .config.config import MQTTConfig


@dataclass
class WriterPerformanceMetrics:
    """Database writer performance metrics"""

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


@dataclass
class WriterHealthStatus:
    """Database writer health status"""

    status: HealthStatus
    records_per_second: float
    batches_per_minute: float
    performance: WriterPerformanceMetrics


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
    value: float | None
    telemetry_type: str
    created: datetime
    data_source: str = "mqtt"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion"""
        return {
            "charger_id": self.charger_id,
            "timestamp": self.timestamp,
            "value": self.value,
            "type": self.telemetry_type,
            "data_source": self.data_source,
            "created": self.created,
        }


@dataclass
class ParseSuccess:
    """Represents a successfully parsed telemetry record"""

    record: TelemetryRecord


@dataclass
class ParseFailure:
    """Represents a failed parsing attempt, with context"""

    reason: str
    is_error: bool  # True for unexpected errors, False for safe skips
    log_message: str
    context: dict[str, Any]


ParseResult = ParseSuccess | ParseFailure


@dataclass
class WriteBatch:
    """Batch of telemetry records for database insertion"""

    records: list[TelemetryRecord] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    status: WriteStatus = WriteStatus.PENDING
    retry_count: int = 0
    last_error: str | None = None

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

    def __init__(
        self,
        config: MQTTConfig,
        session_factory: Callable[[], AsyncSession],
        topic_extractor: TopicMetadataExtractor,
    ):
        self.config = config
        self._session_factory = session_factory
        self.topic_extractor = topic_extractor

        # Batching configuration
        self.batch_size = config.batch_size
        self.batch_timeout = config.batch_timeout
        self.max_retries = 3
        self.retry_delay = 1.0

        # Write queues
        self.pending_batch = WriteBatch()
        self.processing_batches: dict[str, WriteBatch] = {}
        self.failed_batches: list[WriteBatch] = []

        # Performance metrics
        self.total_records_received = 0
        self.total_records_written = 0
        self.total_records_failed = 0
        self.total_batches_processed = 0
        self.total_batches_failed = 0
        self.write_latency_sum = 0.0
        self.write_latency_count = 0

        # Charger status tracking
        self.charger_last_seen: dict[str, datetime] = {}
        self.charger_message_counts: dict[str, int] = defaultdict(int)

        # Background tasks
        self._writer_task: asyncio.Task | None = None
        self._health_task: asyncio.Task | None = None
        self._batch_tasks: set[asyncio.Task] = set()
        self._next_batch_id = 0
        self._shutdown_event = asyncio.Event()
        self._batch_ready_event = asyncio.Event()

        # Logging context
        self._log_context = {"component": "database_writer", "service": "mqtt_proxy"}

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def start(self):
        """Start the database writer"""
        logger.info("event=db_writer.started", extra=self._log_context)

        # Start background tasks
        self._writer_task = asyncio.create_task(self._writer_loop())
        self._health_task = asyncio.create_task(self._health_monitor_loop())

        logger.info(
            "event=db_writer.startup_complete",
            extra={
                **self._log_context,
                "batch_size": self.batch_size,
                "batch_timeout": self.batch_timeout,
                "max_retries": self.max_retries,
            },
        )

    async def stop(self):
        """Stop the database writer"""
        logger.debug("event=db_writer.stopping", extra=self._log_context)

        # Signal shutdown
        self._shutdown_event.set()
        self._batch_ready_event.set()

        # Let the writer loop hand off any pending batch before shutdown drains
        # in-flight write tasks.
        if self._writer_task and not self._writer_task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._writer_task),
                    timeout=max(self.batch_timeout * 2, 5.0),
                )
            except TimeoutError:
                self._writer_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._writer_task
            except asyncio.CancelledError:
                pass

        # Process remaining batches and wait for all started batches to finish.
        pending_batch_size = self.pending_batch.size()
        if pending_batch_size > 0:
            logger.info(
                "event=db_writer.shutdown_flush records_count=%s",
                pending_batch_size,
                extra={**self._log_context, "records_count": pending_batch_size},
            )
            await self._trigger_batch_processing()

        await self._await_batch_tasks()

        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._health_task

        logger.debug("event=db_writer.stopped", extra=self._log_context)

    async def write_telemetry_message(self, message: MQTTMessage):
        """
        Write MQTT telemetry message to database

        Args:
            message: MQTT message containing telemetry data
        """
        # Parse message with explicit result handling
        parse_result = await self._parse_telemetry_message(message)

        if isinstance(parse_result, ParseFailure):
            # Handle failure with centralized logging
            if parse_result.is_error:
                logger.error(
                    parse_result.log_message,
                    extra={**self._log_context, **parse_result.context},
                    exc_info=True,
                )
            else:
                logger.warning(
                    parse_result.log_message,
                    extra={**self._log_context, **parse_result.context},
                )
            return

        # Extract record from success
        record = parse_result.record

        # Add to batch
        self.pending_batch.add_record(record)
        self.total_records_received += 1
        pending_batch_size = self.pending_batch.size()

        # Update charger tracking
        self.charger_last_seen[record.charger_id] = record.timestamp
        self.charger_message_counts[record.charger_id] += 1

        # Log high-frequency messages intelligently
        if self.total_records_received % 100 == 0:
            logger.debug(
                "event=db_writer.record_queued total_received=%s \
                     charger_id=%s telemetry_type=%s batch_size=%s",
                self.total_records_received,
                record.charger_id,
                record.telemetry_type,
                pending_batch_size,
                extra={
                    **self._log_context,
                    "charger_id": record.charger_id,
                    "telemetry_type": record.telemetry_type,
                    "batch_size": pending_batch_size,
                    "total_received": self.total_records_received,
                },
            )

        # Check if batch is ready for processing due to size
        if pending_batch_size >= self.batch_size:
            self._batch_ready_event.set()

    async def _parse_telemetry_message(self, message: MQTTMessage) -> ParseResult:
        """Parse MQTT message and return an explicit success or failure object"""
        try:
            payload = message.payload
            metadata = self.topic_extractor.extract(message.topic, payload)
            if metadata is None:
                return ParseFailure(
                    reason="Topic metadata extraction failed",
                    is_error=False,
                    log_message=(
                        f"Unable to extract metadata from topic: {message.topic}"
                    ),
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
                    context={
                        "charger_id": charger_id,
                        "topic": message.topic,
                    },
                )

            # Extract value and timestamp from payload
            # Parse timestamp
            timestamp_value = payload.get("timestamp")
            if timestamp_value is not None:
                try:
                    if isinstance(timestamp_value, (int, float)):
                        timestamp = datetime.fromtimestamp(
                            timestamp_value,
                            tz=UTC,
                        )
                    else:
                        timestamp_str = str(timestamp_value).strip()
                        if not timestamp_str:
                            raise ValueError("empty timestamp")
                        timestamp = datetime.fromisoformat(
                            timestamp_str.replace("Z", "+00:00")
                        )

                    if timestamp.tzinfo:
                        timestamp = timestamp.astimezone(UTC)
                    else:
                        timestamp = timestamp.replace(tzinfo=UTC)
                except (ValueError, TypeError, OSError) as e:
                    timestamp_context = str(timestamp_value)
                    return ParseFailure(
                        reason="Invalid timestamp format",
                        is_error=False,
                        log_message=f"Invalid timestamp format: {timestamp_context}",
                        context={
                            "charger_id": charger_id,
                            "timestamp": timestamp_context,
                            "error": str(e),
                        },
                    )
            else:
                timestamp = datetime.now(UTC)

            # Parse value
            value = string_to_float(payload.get("value"))

            # Create record
            record = TelemetryRecord(
                charger_id=charger_id,
                timestamp=timestamp,
                value=value,
                telemetry_type=telemetry_type,
                created=datetime.now(UTC),
            )

            return ParseSuccess(record=record)

        except Exception as e:
            return ParseFailure(
                reason="Unexpected parsing error",
                is_error=True,
                log_message=f"Error parsing telemetry message: {e}",
                context={
                    "topic": message.topic,
                    "payload": message.payload,
                    "error": str(e),
                },
            )

    async def _trigger_batch_processing(self):
        """Trigger processing of current batch"""
        if self.pending_batch.size() == 0:
            return None

        # Move current batch to processing
        self._next_batch_id += 1
        batch_id = f"batch_{int(time.time() * 1000)}_{self._next_batch_id}"
        self.processing_batches[batch_id] = self.pending_batch
        self.pending_batch = WriteBatch()

        # Process batch in background
        task = asyncio.create_task(self._process_batch_with_retry(batch_id))
        self._batch_tasks.add(task)
        task.add_done_callback(self._batch_tasks.discard)
        return task

    async def _await_batch_tasks(self) -> None:
        """Wait for all in-flight batch write tasks to settle before shutdown."""
        if not self._batch_tasks:
            return
        done, pending = await asyncio.wait(
            set(self._batch_tasks),
            timeout=self.config.graceful_shutdown_timeout,
        )
        for task in done:
            try:
                task.result()
            except Exception as exc:
                logger.error(
                    "event=db_writer.batch_task_failed_during_shutdown error=%s",
                    exc,
                    extra={**self._log_context, "error": str(exc)},
                    exc_info=True,
                )
        if pending:
            logger.error(
                "event=db_writer.shutdown_pending_batches count=%s",
                len(pending),
                extra={**self._log_context, "pending_batches": len(pending)},
            )
            for task in pending:
                task.cancel()
            for task in pending:
                with suppress(asyncio.CancelledError):
                    await task

    async def _writer_loop(self):
        """Background loop for batch processing"""
        try:
            while not self._shutdown_event.is_set():
                try:
                    # Wait for batch ready event OR timeout
                    await asyncio.wait_for(
                        self._batch_ready_event.wait(), timeout=self.batch_timeout
                    )
                    # Batch ready due to size - process immediately
                    await self._trigger_batch_processing()

                except TimeoutError:
                    # Timeout reached - check for aged batch
                    pending_batch_size = self.pending_batch.size()
                    pending_batch_age = self.pending_batch.get_age_seconds()
                    if (
                        pending_batch_size > 0
                        and pending_batch_age >= self.batch_timeout
                    ):
                        logger.debug(
                            f"Batch timeout reached, "
                            f"processing {pending_batch_size} records",
                            extra={
                                **self._log_context,
                                "batch_size": pending_batch_size,
                                "batch_age": pending_batch_age,
                            },
                        )
                        await self._trigger_batch_processing()

                finally:
                    # Always clear the event for next iteration
                    self._batch_ready_event.clear()

        except asyncio.CancelledError:
            logger.debug(
                "event=db_writer.writer_loop_cancelled", extra=self._log_context
            )
        except Exception as e:
            logger.error(
                "event=db_writer.writer_loop_failed error=%s",
                e,
                extra=self._log_context,
                exc_info=True,
            )

    async def _process_batch_with_retry(self, batch_id: str):
        """Process batch with retry logic"""
        batch = self.processing_batches.get(batch_id)
        if not batch:
            return

        max_attempts = self.max_retries + 1
        batch_size = batch.size()

        for attempt in range(max_attempts):
            try:
                batch.status = (
                    WriteStatus.PROCESSING if attempt == 0 else WriteStatus.RETRYING
                )
                batch.retry_count = attempt

                if attempt > 0:
                    delay = self.config.get_jittered_backoff_delay(attempt - 1)
                    logger.warning(
                        "event=db_writer.batch_retry batch_id=%s batch_size=%s \
                             attempt=%s max_attempts=%s delay_s=%.3f",
                        batch_id,
                        batch_size,
                        attempt + 1,
                        max_attempts,
                        delay,
                        extra={
                            **self._log_context,
                            "batch_id": batch_id,
                            "batch_size": batch_size,
                            "retry_count": attempt,
                            "delay": delay,
                        },
                    )
                    await asyncio.sleep(delay)

                success = await self._process_batch(batch)

                if success:
                    batch.status = WriteStatus.SUCCESS
                    self.processing_batches.pop(batch_id, None)
                    logger.debug(
                        "event=db_writer.batch_success batch_id=%s \
                             batch_size=%s attempt=%s",
                        batch_id,
                        batch_size,
                        attempt + 1,
                        extra={
                            **self._log_context,
                            "batch_id": batch_id,
                            "batch_size": batch_size,
                            "attempt": attempt + 1,
                        },
                    )
                    return

            except Exception as e:
                logger.error(
                    "event=db_writer.batch_attempt_failed batch_id=%s \
                        batch_size=%s attempt=%s error=%s",
                    batch_id,
                    batch_size,
                    attempt + 1,
                    e,
                    extra={
                        **self._log_context,
                        "batch_id": batch_id,
                        "batch_size": batch_size,
                        "attempt": attempt + 1,
                        "error": str(e),
                    },
                    exc_info=True,
                )
                batch.last_error = str(e)

        # All attempts failed
        batch.status = WriteStatus.FAILED
        self.total_records_failed += batch_size
        self.failed_batches.append(batch)
        self.processing_batches.pop(batch_id, None)
        self.total_batches_failed += 1

        logger.error(
            "event=db_writer.batch_failed batch_id=%s batch_size=%s attempts=%s",
            batch_id,
            batch_size,
            max_attempts,
            extra={
                **self._log_context,
                "batch_id": batch_id,
                "batch_size": batch_size,
                "last_error": batch.last_error,
                "charger_ids": list(batch.get_charger_ids()),
            },
        )

    async def _process_batch(self, batch: WriteBatch) -> bool:
        """Process a batch of telemetry records"""
        batch_size = batch.size()
        if batch_size == 0:
            return True

        start_time = time.time()

        charger_ids = batch.get_charger_ids()

        try:
            # Convert records to database format
            records_data = [record.to_dict() for record in batch.records]

            # Perform bulk insert with conflict handling
            stmt = insert(Telemetry).values(records_data)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["charger_id", "timestamp", "type"]
            )

            async with self._session_factory() as session:
                try:
                    await self._upsert_chargers(session, charger_ids)
                    insert_result = await session.execute(stmt)
                    rowcount = insert_result.rowcount
                    records_written = (
                        batch_size
                        if rowcount is None or rowcount < 0
                        else int(rowcount)
                    )
                    if charger_ids:
                        await self._update_charger_statuses(session, charger_ids)
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

            # Update metrics
            # Approximate; conflicts may lower written rows.
            # Use insert result count instead of input size for accurate throughput.
            # Some drivers return None or -1; fallback to batch size to preserve
            # prior semantics where execution counts were unavailable.
            self.total_records_written += records_written
            self.total_batches_processed += 1

            # Track write latency
            write_latency = time.time() - start_time
            self.write_latency_sum += write_latency
            self.write_latency_count += 1

            # Log batch processing with intelligent frequency
            if self.total_batches_processed % 10 == 0 or write_latency > 1.0:
                extra_data = {
                    **self._log_context,
                    "batch_size": records_written,
                    "write_latency": write_latency,
                    "total_batches": self.total_batches_processed,
                    "total_records": self.total_records_written,
                    "avg_latency": self.write_latency_sum / self.write_latency_count,
                    "charger_count": len(charger_ids),
                }

                if write_latency <= 1.0:
                    logger.debug(
                        "event=db_writer.batch_processed batch_size=%s \
                             write_latency_s=%.3f",
                        records_written,
                        write_latency,
                        extra=extra_data,
                    )
                else:
                    logger.warning(
                        "event=db_writer.batch_slow batch_size=%s write_latency_s=%.3f",
                        records_written,
                        write_latency,
                        extra=extra_data,
                    )

            # Performance logging
            log_performance(
                "telemetry_batch_write",
                start_time,
                logger,
            )

            return True

        except IntegrityError as e:
            logger.warning(
                "event=db_writer.batch_integrity_error batch_size=%s error=%s",
                batch_size,
                e,
                extra={
                    **self._log_context,
                    "batch_size": batch_size,
                    "error": str(e),
                },
            )
            await self._update_chargers_after_failure(charger_ids)
            return True  # Treat as success since it's likely just duplicates

        except SQLAlchemyError as e:
            logger.error(
                "event=db_writer.batch_db_error batch_size=%s error=%s",
                batch_size,
                e,
                extra={
                    **self._log_context,
                    "batch_size": batch_size,
                    "error": str(e),
                },
                exc_info=True,
            )
            return False

        except Exception as e:
            logger.error(
                "event=db_writer.batch_unexpected_error batch_size=%s error=%s",
                batch_size,
                e,
                extra={
                    **self._log_context,
                    "batch_size": batch_size,
                    "error": str(e),
                },
                exc_info=True,
            )
            return False

    async def _upsert_chargers(
        self, session: AsyncSession, charger_ids: set[str]
    ) -> None:
        """
        Ensure chargers exist before telemetry inserts and status updates.
        """
        if not charger_ids:
            return

        now = datetime.now(UTC)
        rows = [
            {
                "charger_id": charger_id,
                "online": True,
                "mqtt_connected": True,
                "mqtt_last_message": self.charger_last_seen.get(charger_id, now),
                "last_seen": self._format_last_seen(
                    self.charger_last_seen.get(charger_id, now)
                ),
            }
            for charger_id in charger_ids
        ]

        stmt = (
            insert(Charger)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["charger_id"])
        )
        await session.execute(stmt)

    async def _update_charger_statuses(
        self, session: AsyncSession, charger_ids: set
    ) -> None:
        """Update charger MQTT connection statuses within an active session
        using bulk update"""
        if not charger_ids:
            return

        now = datetime.now(UTC)

        # Build CASE expression to preserve per-charger timestamps
        # Use actual timestamp from charger_last_seen, fallback to current time
        timestamp_case = case(
            *[
                (Charger.charger_id == cid, self.charger_last_seen.get(cid, now))
                for cid in charger_ids
            ],
            else_=now,
        )
        last_seen_case = case(
            *[
                (
                    Charger.charger_id == cid,
                    self._format_last_seen(self.charger_last_seen.get(cid, now)),
                )
                for cid in charger_ids
            ],
            else_=self._format_last_seen(now),
        )

        stmt = (
            update(Charger)
            .where(Charger.charger_id.in_(charger_ids))
            .values(
                mqtt_connected=True,
                mqtt_last_message=timestamp_case,
                last_seen=last_seen_case,
            )
        )

        await session.execute(stmt)

        logger.debug(
            "event=db_writer.charger_status_bulk_updated charger_count=%s",
            len(charger_ids),
            extra={
                **self._log_context,
                "charger_count": len(charger_ids),
            },
        )

    @staticmethod
    def _format_last_seen(value: datetime) -> str:
        """
        Format datetime into a stable ISO string for the legacy text `last_seen` field.
        """
        if value.tzinfo is not None:
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return value.isoformat()

    async def _update_chargers_after_failure(self, charger_ids: set) -> None:
        """Best-effort status update when inserts fail (duplicates, etc.)."""
        if not charger_ids:
            return

        try:
            async with self._session_factory() as session:
                try:
                    await self._update_charger_statuses(session, charger_ids)
                    await session.commit()
                except Exception as exc:
                    await session.rollback()
                    logger.warning(
                        "Failed to update charger statuses after integrity error",
                        extra={
                            **self._log_context,
                            "charger_ids": list(charger_ids),
                            "error": str(exc),
                        },
                    )
        except Exception as exc:
            logger.warning(
                "Unable to create session for post-failure charger updates",
                extra={**self._log_context, "error": str(exc)},
            )

    async def _health_monitor_loop(self):
        """Background health monitoring loop"""
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(self.config.health_monitor_interval)

                # Log health metrics periodically
                metrics = self.get_performance_metrics()
                health = self.get_health_status()

                if health.status != HealthStatus.HEALTHY:
                    logger.warning(
                        f"Database writer health check: {health.status}",
                        extra={
                            **self._log_context,
                            "health_status": health,
                            "performance_metrics": metrics,
                        },
                    )
                elif self.total_batches_processed % 100 == 0:
                    logger.info(
                        f"Database writer health check: {health.status}",
                        extra={
                            **self._log_context,
                            "health_status": health,
                            "performance_metrics": metrics,
                        },
                    )

        except asyncio.CancelledError:
            logger.debug(
                "event=db_writer.health_monitor_cancelled", extra=self._log_context
            )
        except Exception as e:
            logger.error(
                "event=db_writer.health_monitor_failed error=%s",
                e,
                extra=self._log_context,
                exc_info=True,
            )

    def get_performance_metrics(self) -> WriterPerformanceMetrics:
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

        return WriterPerformanceMetrics(
            total_records_received=self.total_records_received,
            total_records_written=self.total_records_written,
            total_records_failed=self.total_records_failed,
            total_batches_processed=self.total_batches_processed,
            total_batches_failed=self.total_batches_failed,
            batch_success_rate=round(success_rate, 2),
            average_write_latency=round(avg_latency, 3),
            pending_batch_size=self.pending_batch.size(),
            processing_batches_count=len(self.processing_batches),
            failed_batches_count=len(self.failed_batches),
            unique_chargers_seen=len(self.charger_last_seen),
            total_messages_by_charger=dict(self.charger_message_counts),
        )

    def get_health_status(self) -> WriterHealthStatus:
        """Get health status for monitoring"""
        metrics = self.get_performance_metrics()

        # Determine health status
        status = HealthStatus.HEALTHY

        # Check for high failure rate
        if metrics.batch_success_rate < 95:
            status = HealthStatus.UNHEALTHY
        elif metrics.batch_success_rate < 98:
            status = HealthStatus.DEGRADED

        # Check for high latency
        if metrics.average_write_latency > 5.0:
            status = HealthStatus.UNHEALTHY
        elif (
            metrics.average_write_latency > 2.0 and status is not HealthStatus.UNHEALTHY
        ):
            status = HealthStatus.DEGRADED

        # Check for too many pending batches
        if metrics.processing_batches_count > 10:
            status = HealthStatus.UNHEALTHY
        elif (
            metrics.processing_batches_count > 5
            and status is not HealthStatus.UNHEALTHY
        ):
            status = HealthStatus.DEGRADED

        return WriterHealthStatus(
            status=status,
            records_per_second=self._calculate_records_per_second(),
            batches_per_minute=self._calculate_batches_per_minute(),
            performance=metrics,
        )

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
