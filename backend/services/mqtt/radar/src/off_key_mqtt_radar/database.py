"""
Database writer for RADAR service

Handles batch writing of anomaly detection results to the database
with error handling and performance optimization.

Note: This module uses RADAR_DATABASE_URL environment variable directly
to avoid depending on off_key_core.db.base which requires the full Settings
class with 23+ environment variables.
"""

import asyncio
import json
import logging
import time
from collections import deque
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from off_key_core.db.table_contracts import (
    monitoring_evidence_table,
    radar_runtime_checkpoints_table,
)
from off_key_core.schemas.radar import RadarOperationalStatus
from sqlalchemy import (
    JSON,
    TIMESTAMP,
    Column,
    Float,
    Table,
    Text,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import MetaData

from .config.config import MQTTRadarConfig
from .config.runtime import get_radar_checkpoint_settings, get_radar_database_settings
from .models import AnomalyResult, ServiceMetrics
from .result_records import PreparedResult, ResultProjector

logger = logging.getLogger(__name__)


# Lazy-initialized async session factory
_radar_async_session_factory = None

# Minimal table mapping used for anomaly inserts without importing
# off_key_core.db.models.
# Importing core models pulls off_key_core.db.base, which initializes global Settings
# and fails in RADAR-only container contexts where non-RADAR env vars are absent.
_anomaly_metadata = MetaData()
ANOMALY_TABLE = Table(
    "anomalies",
    _anomaly_metadata,
    Column("charger_id", Text, primary_key=True),
    Column("timestamp", TIMESTAMP(timezone=True), primary_key=True),
    Column("telemetry_type", Text, primary_key=True),
    Column("service_id", Text, primary_key=True, server_default=text("''")),
    Column("anomaly_type", Text, nullable=False),
    Column("anomaly_value", Float, nullable=False),
    Column("value_type", Text, nullable=True),
    Column("sensor_set", JSON, nullable=True),
)
ANOMALY_IDENTITY_TABLE = Table(
    "anomaly_identity",
    _anomaly_metadata,
    Column(
        "anomaly_id",
        Text,
        primary_key=True,
        server_default=text("gen_random_uuid()::text"),
    ),
    Column("charger_id", Text, nullable=False),
    Column("timestamp", TIMESTAMP(timezone=True), nullable=False),
    Column("telemetry_type", Text, nullable=False),
    Column("service_id", Text, nullable=False, server_default=text("''")),
)
MONITORING_EVIDENCE_TABLE = monitoring_evidence_table(_anomaly_metadata)
RUNTIME_CHECKPOINT_TABLE = radar_runtime_checkpoints_table(_anomaly_metadata)


def get_radar_async_session_factory():
    """
    Get or create async session factory using RADAR_DATABASE_URL env var.

    Falls back to POSTGRES_* when RADAR_DATABASE_URL is not provided to
    remain compatible with existing deployments.

    Raises ValueError if no usable configuration is found.
    """
    global _radar_async_session_factory

    if _radar_async_session_factory is None:
        database_url = get_radar_database_settings().async_database_url

        engine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=0,
        )

        _radar_async_session_factory = sessionmaker(
            bind=engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            class_=AsyncSession,
        )

        logger.info("Created RADAR async session factory")

    return _radar_async_session_factory


class DatabaseWriter:
    """
    Batch database writer for anomaly detection results

    Features:
    - Batch processing for performance
    - Error handling with retry logic
    - Connection pooling and health monitoring
    - Metrics tracking
    """

    def __init__(
        self,
        config: MQTTRadarConfig,
        session_factory=None,
        *,
        managed_checkpoints: bool = False,
    ):
        self.config = config
        self.managed_checkpoints = managed_checkpoints
        self.projector = ResultProjector()
        self.total_rejected = 0
        # Session factory is created lazily to avoid requiring DB env vars
        # when database writing is disabled.
        self.session_factory = session_factory

        # Batch processing
        self.write_queue: list[AnomalyResult] = []
        self.last_write_time = time.time()
        self.last_persisted_at: datetime | None = None
        # Entries remain owned during flush/retry, so a small in-flight batch
        # cannot disappear from persistence-lag reporting.
        self._pending_receipts: dict[int, deque[float]] = {}

        # Performance tracking
        self.total_written = 0
        self.total_evidence_written = 0
        self.total_errors = 0
        self.write_times = deque(maxlen=100)

        # Control
        self._writer_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._flush_event = asyncio.Event()
        self._queue_changed = asyncio.Condition()
        self._in_flight = 0
        self._flush_lock = asyncio.Lock()

        logger.info("event=radar.db_writer_initialized")

    async def start(self):
        """Start the database writer"""
        if not self.config.db_write_enabled:
            logger.debug("event=radar.db_writer_disabled")
            return

        if self._writer_task is not None and not self._writer_task.done():
            return

        self._shutdown_event.clear()
        self._flush_event.clear()

        # Initialize session factory lazily to avoid failing when disabled
        if self.session_factory is None:
            self.session_factory = get_radar_async_session_factory()

        # Test database connection
        await self._test_connection()

        # Start writer task
        self._writer_task = asyncio.create_task(self._writer_loop())

        logger.info("event=radar.db_writer_started")

    async def stop(self):
        """Stop the database writer and flush remaining records"""
        logger.info("event=radar.db_writer_stopping")

        # Signal shutdown
        self._shutdown_event.set()
        self._flush_event.set()
        async with self._queue_changed:
            self._queue_changed.notify_all()

        cancelled_error: asyncio.CancelledError | None = None

        # Let the writer loop finish any in-progress flush before cancelling it.
        # The shield is intentional: if the caller cancels stop(), the writer task
        # must not be cancelled while a batch snapshot may be out of the queue.
        if self._writer_task:
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._writer_task),
                    timeout=max(self.config.db_batch_timeout * 2, 5.0),
                )
            except TimeoutError:
                self._writer_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._writer_task
            except asyncio.CancelledError as exc:
                cancelled_error = exc

        # Flush remaining records
        await asyncio.shield(self._flush_batch())

        logger.info("event=radar.db_writer_stopped")
        if cancelled_error is not None:
            raise cancelled_error

    async def write_result(self, result: AnomalyResult):
        """Queue a static inference result for evidence and optional alarm writing."""
        if not self.config.db_write_enabled:
            return

        async with self._queue_changed:
            await self._queue_changed.wait_for(
                lambda: (
                    self._shutdown_event.is_set()
                    or len(self.write_queue) + self._in_flight
                    < self.config.max_queue_size
                )
            )
            if self._shutdown_event.is_set():
                raise RuntimeError("Database writer is stopped")
            self.write_queue.append(result)
            self._pending_receipts.setdefault(id(result), deque()).append(
                time.monotonic()
            )
            queue_size = len(self.write_queue)
            should_flush = (
                queue_size >= min(self.config.db_batch_size, self.config.max_queue_size)
                or (time.time() - self.last_write_time) > self.config.db_batch_timeout
            )

        # Keep the MQTT consumer off the database I/O path during normal operation.
        if should_flush:
            self._flush_event.set()

    async def write_anomaly(self, result: AnomalyResult):
        """Queue a result; retained as the public writer entry point."""
        await self.write_result(result)

    async def load_checkpoint(self, service_id: str) -> dict[str, Any] | None:
        """Require the migrated durable store before a managed worker subscribes."""
        if self.session_factory is None:
            self.session_factory = get_radar_async_session_factory()
        async with self.session_factory() as session:
            result = await session.execute(
                select(RUNTIME_CHECKPOINT_TABLE).where(
                    RUNTIME_CHECKPOINT_TABLE.c.service_id == service_id
                )
            )
            row = result.mappings().one_or_none()
            return dict(row) if row is not None else None

    async def commit_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        """Commit frozen model state and all pending evidence in one transaction.

        The MQTT consumer is the only producer while this barrier is awaited.
        Earlier background batches have committed before this lock is acquired.
        Any failed transaction retains its original results for retry.
        """
        if not self.config.db_write_enabled:
            raise RuntimeError("Database checkpoint storage requires database writes")
        if self.session_factory is None:
            self.session_factory = get_radar_async_session_factory()
        async with self._flush_lock:
            async with self._queue_changed:
                pending = list(self.write_queue)
                self.write_queue.clear()
                self._in_flight = len(pending)
            try:
                prepared = [
                    self._prepare_managed_result(result)
                    for result in pending
                    if result.should_persist
                ]
                anomalies = [row for item in prepared for row in item.anomalies]
                identities = [row for item in prepared for row in item.identities]
                evidence = [row for item in prepared for row in item.evidence]
                async with self.session_factory() as session:
                    await self._execute_upsert(session, anomalies, identities)
                    await self._execute_evidence_upsert(session, evidence)
                    statement = pg_insert(RUNTIME_CHECKPOINT_TABLE).values(checkpoint)
                    statement = statement.on_conflict_do_update(
                        index_elements=["service_id"],
                        set_={
                            name: getattr(statement.excluded, name)
                            for name in checkpoint
                            if name != "service_id"
                        },
                    )
                    await session.execute(statement)
                    await session.commit()
                self.total_written += len(anomalies)
                self.total_evidence_written += len(evidence)
                self.last_write_time = time.time()
                self._complete_results(pending, bool(anomalies or evidence))
            except BaseException:
                await self._requeue_results(pending)
                self.total_errors += 1
                raise
            finally:
                async with self._queue_changed:
                    self._in_flight = 0
                    self._queue_changed.notify_all()

    async def write_service_metrics(self, metrics: dict[str, Any]):
        """Write service performance metrics"""
        if not self.config.db_write_enabled:
            return

        try:
            if self.session_factory is None:
                self.session_factory = get_radar_async_session_factory()

            async with self.session_factory() as session:
                service_metrics = ServiceMetrics(
                    timestamp=datetime.now(),
                    total_messages_processed=metrics.get("total_messages_processed", 0),
                    total_anomalies_detected=metrics.get("total_anomalies_detected", 0),
                    anomaly_rate=metrics.get("anomaly_rate", 0.0),
                    avg_processing_time_ms=metrics.get("avg_processing_time_ms"),
                    throughput_per_second=metrics.get("throughput_per_second"),
                    memory_usage_mb=metrics.get("memory_usage_mb"),
                    error_count=metrics.get("error_count", 0),
                    error_rate=metrics.get("error_rate", 0.0),
                    service_status=metrics.get("service_status", "unknown"),
                    active_alerts=metrics.get("active_alerts", []),
                )

                session.add(service_metrics)
                await self._update_service_operational_status(
                    session, metrics.get("operational_status")
                )
                await session.commit()

        except Exception as e:
            logger.error(
                "event=radar.db_metrics_write_failed error=%s",
                str(e),
                exc_info=True,
            )
            self.total_errors += 1

    async def _update_service_operational_status(
        self,
        session: AsyncSession,
        status: Any,
    ) -> None:
        if not isinstance(status, dict):
            return

        service_id = get_radar_checkpoint_settings().SERVICE_ID
        if not service_id:
            return

        normalized = RadarOperationalStatus(**status)
        updated_at = normalized.updated_at or datetime.now(UTC)
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        payload = normalized.model_copy(update={"updated_at": updated_at}).model_dump(
            mode="json", exclude_none=True
        )

        await session.execute(
            text(
                """
                UPDATE services
                SET operational_stage = :stage,
                    operational_status = CAST(:status_payload AS jsonb),
                    operational_updated_at = :updated_at
                WHERE id = :service_id
                """
            ),
            {
                "stage": normalized.stage,
                "status_payload": json.dumps(payload),
                "updated_at": updated_at,
                "service_id": service_id,
            },
        )

    async def _test_connection(self):
        """Test database connection"""
        try:
            if self.session_factory is None:
                self.session_factory = get_radar_async_session_factory()

            async with self.session_factory() as session:
                # Simple test query
                result = await session.execute(text("SELECT 1"))
                result.fetchone()
                logger.info("event=radar.db_connection_test_success")
        except Exception as e:
            logger.error(
                "event=radar.db_connection_test_failed error=%s",
                str(e),
                exc_info=True,
            )
            raise

    async def _writer_loop(self):
        """Main writer loop for batch processing"""
        logger.info("event=radar.db_writer_loop_started")

        try:
            while True:
                with suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._flush_event.wait(),
                        timeout=self.config.db_batch_timeout,
                    )

                self._flush_event.clear()
                await self._flush_batch()
                if self._shutdown_event.is_set():
                    break

        except asyncio.CancelledError:
            logger.debug("event=radar.db_writer_loop_cancelled")
        except Exception as e:
            logger.error(
                "event=radar.db_writer_loop_error error=%s",
                str(e),
                exc_info=True,
            )
        finally:
            self._shutdown_event.set()
            async with self._queue_changed:
                self._queue_changed.notify_all()

        logger.info("event=radar.db_writer_loop_stopped")

    async def _execute_upsert(
        self,
        session: AsyncSession,
        anomaly_records: list[dict[str, Any]],
        identity_records: list[dict[str, Any]],
    ) -> None:
        if not anomaly_records:
            return

        # Use INSERT ... ON CONFLICT DO NOTHING for idempotency
        # Scope idempotency to one monitor, including simultaneous vector alarms.
        stmt = pg_insert(ANOMALY_TABLE).values(anomaly_records)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["charger_id", "timestamp", "telemetry_type", "service_id"]
        )
        await session.execute(stmt)

        identity_stmt = pg_insert(ANOMALY_IDENTITY_TABLE).values(identity_records)
        identity_stmt = identity_stmt.on_conflict_do_nothing(
            index_elements=["charger_id", "timestamp", "telemetry_type", "service_id"]
        )
        await session.execute(identity_stmt)

    async def _execute_evidence_upsert(
        self,
        session: AsyncSession,
        evidence_records: list[dict[str, Any]],
    ) -> None:
        if not evidence_records:
            return
        statement = pg_insert(MONITORING_EVIDENCE_TABLE).values(evidence_records)
        statement = statement.on_conflict_do_nothing(
            index_elements=["service_id", "timestamp", "sequence_number"]
        )
        await session.execute(statement)

    async def _flush_batch(self):
        """Flush current batch to core anomalies table"""
        async with self._flush_lock:
            async with self._queue_changed:
                if not self.write_queue:
                    return

                batch_snapshot = list(self.write_queue)
                del self.write_queue[: len(batch_snapshot)]
                self._in_flight = len(batch_snapshot)

            try:
                await self._persist_snapshot(batch_snapshot)
            finally:
                async with self._queue_changed:
                    self._in_flight = 0
                    self._queue_changed.notify_all()

    async def _persist_snapshot(self, batch_snapshot: list[AnomalyResult]) -> None:
        """Retain ownership until a snapshot is written, rejected, or requeued."""
        try:
            if self.session_factory is None:
                self.session_factory = get_radar_async_session_factory()
            prepared = self._prepare_results(batch_snapshot)
        except asyncio.CancelledError:
            await self._requeue_results(batch_snapshot)
            raise
        except Exception:
            self.total_errors += 1
            logger.exception("event=radar.db_batch_preparation_failed")
            await self._requeue_results(batch_snapshot)
            return

        persistence_candidates = [item.result for item in prepared]
        anomaly_records = [row for item in prepared for row in item.anomalies]
        identity_records = [row for item in prepared for row in item.identities]
        evidence_records = [row for item in prepared for row in item.evidence]
        batch_size = len(batch_snapshot)
        anomaly_count = len(anomaly_records)
        start_time = time.time()

        try:
            if anomaly_records or evidence_records:
                async with self.session_factory() as session:
                    await self._execute_upsert(
                        session, anomaly_records, identity_records
                    )
                    await self._execute_evidence_upsert(session, evidence_records)
                    await session.commit()

                    logger.info(
                        "event=radar.db_batch_written "
                        "anomaly_count=%s evidence_count=%s batch_size=%s",
                        anomaly_count,
                        len(evidence_records),
                        batch_size,
                        extra={
                            "anomaly_types": sorted(
                                {record["anomaly_type"] for record in anomaly_records}
                            )
                        },
                    )

            # Update statistics
            write_time = time.time() - start_time
            self.write_times.append(write_time)
            self.total_written += anomaly_count
            self.total_evidence_written += len(evidence_records)
            self.last_write_time = time.time()
            self._complete_results(
                persistence_candidates, bool(anomaly_records or evidence_records)
            )

        except asyncio.CancelledError:
            await self._requeue_results(persistence_candidates)
            raise
        except Exception as e:
            logger.error(
                "event=radar.db_batch_write_failed anomaly_count=%s error=%s",
                anomaly_count,
                str(e),
                exc_info=True,
            )
            self.total_errors += 1

            try:
                retry_succeeded = await self._retry_failed_batch(
                    batch_snapshot=persistence_candidates
                )
                if not retry_succeeded:
                    await self._requeue_results(persistence_candidates)
            except asyncio.CancelledError:
                await self._requeue_results(persistence_candidates)
                raise
            except Exception as retry_exc:
                await self._requeue_results(persistence_candidates)
                self.total_errors += 1
                logger.error(
                    "event=radar.db_retry_unexpected_exception "
                    "requeued_count=%s error=%s",
                    len(batch_snapshot),
                    str(retry_exc),
                    exc_info=True,
                )

    def _prepare_results(self, results: list[AnomalyResult]) -> list[PreparedResult]:
        prepared = []
        for result in results:
            try:
                if result.should_persist:
                    prepared.append(
                        self._prepare_managed_result(result)
                        if self.managed_checkpoints
                        else self.projector.prepare(result)
                    )
                else:
                    self._release_pending([result])
            except (ValueError, TypeError, AttributeError, OverflowError):
                self.total_errors += 1
                self.total_rejected += 1
                if self.managed_checkpoints:
                    raise
                self._release_pending([result])
                logger.exception(
                    "event=radar.db_result_rejected topic=%s timestamp=%s",
                    result.topic,
                    result.timestamp,
                )
        return prepared

    def _prepare_managed_result(self, result: AnomalyResult) -> PreparedResult:
        prepared = self.projector.prepare(result)
        if not prepared.evidence:
            raise ValueError("Managed inference result is missing valid evidence")
        return prepared

    async def _requeue_results(self, results: list[AnomalyResult]) -> None:
        if not results:
            return
        async with self._queue_changed:
            self.write_queue = list(results) + self.write_queue

    async def _retry_failed_batch(self, *, batch_snapshot: list[AnomalyResult]) -> bool:
        """Retry writing failed batch with exponential backoff.

        Remove committed results from the snapshot so the outer flush only
        requeues results that still need writing.
        """
        max_retries = 3
        base_delay = 1.0

        if self.session_factory is None:
            self.session_factory = get_radar_async_session_factory()

        pending_index = 0
        # Process in chunks of 10
        while pending_index < len(batch_snapshot):
            retry_batch = batch_snapshot[pending_index : pending_index + 10]
            retry_delay = base_delay
            success = False
            anomaly_records = self.projector._build_records(
                [result for result in retry_batch if result.is_anomaly]
            )
            anomaly_rows, identity_records = anomaly_records
            evidence_records = self.projector._build_evidence_records(retry_batch)

            for attempt in range(max_retries):
                try:
                    await asyncio.sleep(retry_delay)

                    async with self.session_factory() as session:
                        await self._execute_upsert(
                            session,
                            anomaly_rows,
                            identity_records,
                        )
                        await self._execute_evidence_upsert(session, evidence_records)
                        await session.commit()

                        self.total_written += len(anomaly_rows)
                        self.total_evidence_written += len(evidence_records)
                        self.last_write_time = time.time()
                        self._complete_results(
                            retry_batch, bool(anomaly_rows or evidence_records)
                        )
                        logger.info(
                            "event=radar.db_retry_batch_written count=%s",
                            len(retry_batch),
                        )
                        success = True
                        break  # Exit retry loop on success

                except Exception as e:
                    logger.error(
                        "event=radar.db_retry_attempt_failed attempt=%s error=%s",
                        attempt + 1,
                        str(e),
                        exc_info=True,
                    )
                    retry_delay *= 2  # Exponential backoff

            if success:
                del batch_snapshot[pending_index : pending_index + len(retry_batch)]
            else:
                logger.error(
                    "event=radar.db_retry_exhausted requeued_count=%s max_retries=%s",
                    len(retry_batch),
                    max_retries,
                )
                self.total_errors += 1
                pending_index += len(retry_batch)

        return not batch_snapshot

    def _complete_results(
        self, results: list[AnomalyResult], has_records: bool
    ) -> None:
        if has_records:
            self.last_persisted_at = datetime.now(UTC)
        self._release_pending(results)

    def _release_pending(self, results: list[AnomalyResult]) -> None:
        """Release queue-age ownership after a result commits or is rejected."""
        for result in results:
            receipts = self._pending_receipts.get(id(result))
            if receipts:
                receipts.popleft()
                if not receipts:
                    del self._pending_receipts[id(result)]

    def _persistence_activity(self) -> dict[str, Any]:
        oldest = min(
            (receipts[0] for receipts in self._pending_receipts.values()),
            default=None,
        )
        return {
            "last_persisted_at": self.last_persisted_at.isoformat()
            if self.last_persisted_at
            else None,
            "oldest_pending_age_seconds": max(time.monotonic() - oldest, 0.0)
            if oldest is not None
            else None,
            "persistence_timeout_seconds": max(
                self.config.sensor_freshness_seconds, self.config.db_batch_timeout * 2
            ),
        }

    def get_performance_metrics(self) -> dict[str, Any]:
        """Get database writer performance metrics"""
        avg_write_time = 0.0
        if self.write_times:
            avg_write_time = sum(self.write_times) / len(self.write_times)

        throughput = 0.0
        if avg_write_time > 0:
            avg_batch_size = self.config.db_batch_size
            throughput = avg_batch_size / avg_write_time

        return {
            "total_written": self.total_written,
            "total_evidence_written": self.total_evidence_written,
            "total_errors": self.total_errors,
            "total_rejected": self.total_rejected,
            "error_rate": self.total_errors
            / max(self.total_written + self.total_errors, 1),
            "queue_size": len(self.write_queue) + self._in_flight,
            "avg_write_time_seconds": avg_write_time,
            "throughput_per_second": throughput,
            "last_write_time": datetime.fromtimestamp(self.last_write_time).isoformat(),
            "write_enabled": self.config.db_write_enabled,
            **self._persistence_activity(),
        }

    def get_health_status(self) -> dict[str, Any]:
        """Get database writer health status"""
        activity = self._persistence_activity()
        if not self.config.db_write_enabled:
            return {
                "status": "disabled",
                "reason": "write_disabled_in_config",
                **activity,
            }

        error_rate = self.total_errors / max(self.total_written + self.total_errors, 1)
        queue_usage = (
            len(self.write_queue) + self._in_flight
        ) / self.config.max_queue_size

        pending_age = activity["oldest_pending_age_seconds"]
        if (
            pending_age is not None
            and pending_age > activity["persistence_timeout_seconds"]
        ):
            return {"status": "degraded", "reason": "persistence_stalled", **activity}

        if error_rate > 0.1:  # > 10% error rate
            return {
                "status": "unhealthy",
                "reason": "high_error_rate",
                "error_rate": error_rate,
                **activity,
            }
        if queue_usage > 0.8:  # Queue building up
            return {
                "status": "degraded",
                "reason": "queue_building_up",
                "queue_usage": queue_usage,
                **activity,
            }
        if not self._writer_task or self._writer_task.done():
            return {"status": "unhealthy", "reason": "writer_task_stopped", **activity}
        return {
            "status": "healthy",
            "reason": "ok",
            "queue_size": len(self.write_queue) + self._in_flight,
            "error_rate": error_rate,
            **activity,
        }


async def ensure_radar_metrics_tables():
    """Ensure RADAR service metrics tables exist.

    Note: Anomalies are now written to the core 'anomalies' table
    (TimescaleDB hypertable) managed by off_key_core. This function only
    creates auxiliary tables for service metrics and model checkpoints.
    """
    try:
        session_factory = get_radar_async_session_factory()
        async with session_factory() as session:
            # Check if radar_service_metrics table exists
            result = await session.execute(
                text("SELECT to_regclass('radar_service_metrics')")
            )
            metrics_table_exists = result.scalar() is not None

            if not metrics_table_exists:
                logger.info("event=radar.db_metrics_tables_creating")

                # Create radar_service_metrics table
                await session.execute(
                    text(
                        """
                    CREATE TABLE IF NOT EXISTS radar_service_metrics (
                        id SERIAL PRIMARY KEY,
                        timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
                        total_messages_processed INTEGER NOT NULL DEFAULT 0,
                        total_anomalies_detected INTEGER NOT NULL DEFAULT 0,
                        anomaly_rate FLOAT NOT NULL DEFAULT 0.0,
                        avg_processing_time_ms FLOAT,
                        throughput_per_second FLOAT,
                        memory_usage_mb FLOAT,
                        error_count INTEGER NOT NULL DEFAULT 0,
                        error_rate FLOAT NOT NULL DEFAULT 0.0,
                        service_status VARCHAR(20) NOT NULL,
                        active_alerts JSONB
                    )
                """
                    )
                )

                # Create radar_model_checkpoints table
                await session.execute(
                    text(
                        """
                    CREATE TABLE IF NOT EXISTS radar_model_checkpoints (
                        id SERIAL PRIMARY KEY,
                        model_type VARCHAR(50) NOT NULL,
                        model_version VARCHAR(50) NOT NULL,
                        checkpoint_path VARCHAR(500) NOT NULL,
                        processed_count INTEGER NOT NULL DEFAULT 0,
                        anomaly_count INTEGER NOT NULL DEFAULT 0,
                        anomaly_rate FLOAT NOT NULL DEFAULT 0.0,
                        avg_processing_time FLOAT,
                        memory_usage_mb FLOAT,
                        created_timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
                        config_snapshot JSONB
                    )
                """
                    )
                )

                # Create index for better performance
                await session.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS "
                        "idx_radar_service_metrics_timestamp "
                        "ON radar_service_metrics(timestamp)"
                    )
                )

                logger.info("event=radar.db_metrics_tables_created")
            else:
                logger.debug("event=radar.db_metrics_tables_exist")

            await session.commit()

        logger.info("event=radar.db_table_verification_completed")

    except Exception as e:
        logger.error(
            "event=radar.db_table_verification_failed error=%s",
            str(e),
            exc_info=True,
        )
        logger.warning(
            "Continuing without table creation - "
            "metrics tables should be handled by migrations or manual setup"
        )
