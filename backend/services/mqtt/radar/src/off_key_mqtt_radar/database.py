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
import math
import time
from collections import deque
from collections.abc import Iterable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from off_key_core.db.table_contracts import monitoring_evidence_table
from off_key_core.schemas.radar import RadarOperationalStatus
from off_key_core.utils.mqtt_topics import TopicMetadataExtractor
from sqlalchemy import (
    JSON,
    TIMESTAMP,
    Column,
    Float,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import MetaData

from .config.config import MQTTRadarConfig
from .config.runtime import get_radar_checkpoint_settings, get_radar_database_settings
from .models import AnomalyResult, ServiceMetrics

logger = logging.getLogger(__name__)
MULTIVARIATE_TELEMETRY_TYPE = "__multivariate__"


def _optional_finite_float(value: Any) -> float | None:
    """Return a JSON/database-safe finite float or ``None``."""
    if not isinstance(value, (int, float)):
        return None
    normalized = float(value)
    return normalized if math.isfinite(normalized) else None


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
)
MONITORING_EVIDENCE_TABLE = monitoring_evidence_table(_anomaly_metadata)


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
            pool_size=5,
            max_overflow=10,
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

    def __init__(self, config: MQTTRadarConfig, session_factory=None):
        self.config = config
        self.topic_extractor = TopicMetadataExtractor()
        # Session factory is created lazily to avoid requiring DB env vars
        # when database writing is disabled.
        self.session_factory = session_factory

        # Batch processing
        self.write_queue: list[AnomalyResult] = []
        self.last_write_time = time.time()

        # Performance tracking
        self.total_written = 0
        self.total_evidence_written = 0
        self.total_errors = 0
        self.write_times = deque(maxlen=100)

        # Control
        self._writer_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._queue_lock = asyncio.Lock()
        self._flush_lock = asyncio.Lock()

        logger.info("event=radar.db_writer_initialized")

    async def start(self):
        """Start the database writer"""
        if not self.config.db_write_enabled:
            logger.debug("event=radar.db_writer_disabled")
            return

        self._shutdown_event.clear()

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

        async with self._queue_lock:
            self.write_queue.append(result)
            should_flush = (
                len(self.write_queue) >= self.config.db_batch_size
                or (time.time() - self.last_write_time) > self.config.db_batch_timeout
            )

        # Check if we should flush batch
        if should_flush:
            await self._flush_batch()

    async def write_anomaly(self, result: AnomalyResult):
        """Queue a result; retained as the public writer entry point."""
        await self.write_result(result)

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
            while not self._shutdown_event.is_set():
                try:
                    # Wait for batch timeout
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self.config.db_batch_timeout,
                    )
                    # Shutdown event was set
                    break
                except TimeoutError:
                    # Timeout reached, check if we should flush
                    if (
                        self.write_queue
                        and (time.time() - self.last_write_time)
                        > self.config.db_batch_timeout
                    ):
                        await self._flush_batch()

        except asyncio.CancelledError:
            logger.debug("event=radar.db_writer_loop_cancelled")
        except Exception as e:
            logger.error(
                "event=radar.db_writer_loop_error error=%s",
                str(e),
                exc_info=True,
            )

        logger.info("event=radar.db_writer_loop_stopped")

    def _extract_telemetry_type(
        self, topic: str, payload: dict[str, Any] | None = None
    ) -> str:
        """Extract telemetry type from MQTT topic."""
        metadata = self.topic_extractor.extract(topic=topic, payload=payload)
        return metadata.telemetry_type if metadata else "unknown"

    def _derive_telemetry_type(self, result: AnomalyResult) -> str:
        """Resolve canonical telemetry type for anomaly persistence."""
        alignment_context = (result.context or {}).get("alignment", {})
        if bool(alignment_context.get("aligned_vector")):
            return MULTIVARIATE_TELEMETRY_TYPE
        return self._extract_telemetry_type(result.topic, result.raw_data)

    @staticmethod
    def _is_static_conformal_result(result: AnomalyResult) -> bool:
        return isinstance((result.context or {}).get("static_conformal"), dict)

    @staticmethod
    def _is_static_ready_result(result: AnomalyResult) -> bool:
        static_context = (result.context or {}).get("static_conformal")
        return (
            isinstance(static_context, dict) and static_context.get("phase") == "ready"
        )

    @staticmethod
    def _derive_anomaly_type(result: AnomalyResult) -> str:
        """Map detector output to stored anomaly semantics."""
        alignment_context = (result.context or {}).get("alignment", {})
        if DatabaseWriter._is_static_conformal_result(result):
            if bool(alignment_context.get("aligned_vector")):
                return "ml_conformal_static_multivariate"
            return "ml_conformal_static_univariate"
        if bool(alignment_context.get("aligned_vector")):
            return "ml_tailprob_multivariate"
        return "ml_tailprob_univariate"

    @staticmethod
    def _derive_anomaly_value(result: AnomalyResult) -> float:
        """Persist the p-value used by the active detector when available."""
        static_context = (result.context or {}).get("static_conformal", {})
        conformal_pvalue = static_context.get("p_value")
        if isinstance(conformal_pvalue, (int, float)):
            conformal_pvalue = float(conformal_pvalue)
            if math.isfinite(conformal_pvalue):
                return conformal_pvalue

        score_window = (result.context or {}).get("score_window", {})
        tail_pvalue = score_window.get("tail_pvalue")
        if isinstance(tail_pvalue, (int, float)):
            tail_pvalue = float(tail_pvalue)
            if math.isfinite(tail_pvalue):
                return tail_pvalue
        return float(result.anomaly_score)

    @staticmethod
    def _normalize_sensor_set(value: Any) -> list[str] | None:
        if isinstance(value, dict):
            iterable = value.keys()
        elif isinstance(value, set):
            iterable = sorted(value)
        elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
            iterable = value
        else:
            return None

        sensors = []
        seen = set()
        for item in iterable:
            sensor = str(item).strip() if item is not None else ""
            if sensor and sensor not in seen:
                sensors.append(sensor)
                seen.add(sensor)
        return sensors or None

    def _derive_sensor_set(self, result: AnomalyResult) -> list[str] | None:
        """Resolve the exact telemetry streams involved in a stored anomaly."""
        alignment_context = (result.context or {}).get("alignment", {})
        required_sensors = self._normalize_sensor_set(
            alignment_context.get("required_sensors")
        )
        if required_sensors and (
            bool(alignment_context.get("aligned_vector")) or len(required_sensors) == 1
        ):
            return required_sensors

        feature_source = result.raw_data if isinstance(result.raw_data, dict) else {}
        feature_sensors = self._normalize_sensor_set(feature_source.keys())
        if bool(alignment_context.get("aligned_vector")) and feature_sensors:
            return feature_sensors

        telemetry_type = self._extract_telemetry_type(result.topic, result.raw_data)
        if telemetry_type and telemetry_type != "unknown":
            return [telemetry_type]

        return feature_sensors

    def _build_records(
        self,
        results: list[AnomalyResult],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        anomaly_records = []
        for result in results:
            anomaly_records.append(
                {
                    "charger_id": result.charger_id or "unknown",
                    "timestamp": result.timestamp,
                    "telemetry_type": self._derive_telemetry_type(result),
                    "anomaly_type": self._derive_anomaly_type(result),
                    "anomaly_value": self._derive_anomaly_value(result),
                    "value_type": (
                        "conformal_pvalue"
                        if self._is_static_conformal_result(result)
                        else "tail_pvalue"
                    ),
                    "sensor_set": self._derive_sensor_set(result),
                }
            )
        identity_records = [
            {
                "charger_id": record["charger_id"],
                "timestamp": record["timestamp"],
                "telemetry_type": record["telemetry_type"],
            }
            for record in anomaly_records
        ]
        return anomaly_records, identity_records

    def _build_evidence_records(
        self, results: list[AnomalyResult]
    ) -> list[dict[str, Any]]:
        service_id = get_radar_checkpoint_settings().SERVICE_ID
        if not service_id:
            return []

        records = []
        for result in results:
            if not self._is_static_ready_result(result):
                continue
            context = (result.context or {}).get("static_conformal", {})
            p_value = context.get("p_value")
            sequence_number = context.get("tested_count")
            threshold = context.get("restarted_ville_threshold")
            if not isinstance(p_value, (int, float)) or not math.isfinite(p_value):
                continue
            if not isinstance(sequence_number, int) or sequence_number < 1:
                continue
            if not isinstance(threshold, (int, float)) or not math.isfinite(threshold):
                continue

            records.append(
                {
                    "service_id": service_id,
                    "timestamp": result.timestamp,
                    "sequence_number": sequence_number,
                    "charger_id": result.charger_id or "unknown",
                    "sensor_set": self._derive_sensor_set(result) or [],
                    "p_value": float(p_value),
                    "e_value": _optional_finite_float(context.get("e_value")),
                    "e_value_is_infinite": bool(
                        context.get("e_value_is_infinite", False)
                    ),
                    "log_e_value": _optional_finite_float(context.get("log_e_value")),
                    "restarted_martingale": _optional_finite_float(
                        context.get("restarted_martingale")
                    ),
                    "restarted_martingale_is_infinite": bool(
                        context.get("restarted_martingale_is_infinite", False)
                    ),
                    "log_restarted_martingale": _optional_finite_float(
                        context.get("log_restarted_martingale")
                    ),
                    "threshold": float(threshold),
                    "alarm": bool(context.get("alarm_fired", False)),
                }
            )
        return records

    async def _execute_upsert(
        self,
        session: AsyncSession,
        anomaly_records: list[dict[str, Any]],
        identity_records: list[dict[str, Any]],
    ) -> None:
        if not anomaly_records:
            return

        # Use INSERT ... ON CONFLICT DO NOTHING for idempotency
        # (composite PK: charger_id, timestamp, telemetry_type)
        stmt = pg_insert(ANOMALY_TABLE).values(anomaly_records)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["charger_id", "timestamp", "telemetry_type"]
        )
        await session.execute(stmt)

        identity_stmt = pg_insert(ANOMALY_IDENTITY_TABLE).values(identity_records)
        identity_stmt = identity_stmt.on_conflict_do_nothing(
            index_elements=["charger_id", "timestamp", "telemetry_type"]
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
            async with self._queue_lock:
                if not self.write_queue:
                    return

                batch_snapshot = list(self.write_queue)
                del self.write_queue[: len(batch_snapshot)]

            if self.session_factory is None:
                self.session_factory = get_radar_async_session_factory()

            persistence_candidates = self._persistence_candidates(batch_snapshot)
            # Only write actual anomalies (is_anomaly=True)
            anomalies_to_write = [r for r in persistence_candidates if r.is_anomaly]
            evidence_records = self._build_evidence_records(batch_snapshot)
            batch_size = len(batch_snapshot)
            anomaly_count = len(anomalies_to_write)
            start_time = time.time()

            try:
                if anomalies_to_write or evidence_records:
                    anomaly_records, identity_records = self._build_records(
                        anomalies_to_write
                    )
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
                                    {
                                        record["anomaly_type"]
                                        for record in anomaly_records
                                    }
                                )
                            },
                        )

                # Update statistics
                write_time = time.time() - start_time
                self.write_times.append(write_time)
                self.total_written += anomaly_count
                self.total_evidence_written += len(evidence_records)
                self.last_write_time = time.time()

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

    @staticmethod
    def _persistence_candidates(
        batch_snapshot: list[AnomalyResult],
    ) -> list[AnomalyResult]:
        return [
            result
            for result in batch_snapshot
            if result.is_anomaly or DatabaseWriter._is_static_ready_result(result)
        ]

    async def _requeue_results(self, results: list[AnomalyResult]) -> None:
        if not results:
            return
        async with self._queue_lock:
            self.write_queue = list(results) + self.write_queue

    async def _retry_failed_batch(self, *, batch_snapshot: list[AnomalyResult]) -> bool:
        """Retry writing failed batch with exponential backoff.

        The outer flush retains ownership of the snapshot and live queue.
        """
        max_retries = 3
        base_delay = 1.0

        if self.session_factory is None:
            self.session_factory = get_radar_async_session_factory()

        results_to_retry = self._persistence_candidates(batch_snapshot)

        if not results_to_retry:
            return True

        exhausted_results: list[AnomalyResult] = []
        # Process in chunks of 10
        while results_to_retry:
            retry_batch = results_to_retry[:10]
            retry_delay = base_delay
            success = False
            anomaly_records = self._build_records(
                [result for result in retry_batch if result.is_anomaly]
            )
            anomaly_rows, identity_records = anomaly_records
            evidence_records = self._build_evidence_records(retry_batch)

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

            if not success:
                logger.error(
                    "event=radar.db_retry_exhausted requeued_count=%s max_retries=%s",
                    len(retry_batch),
                    max_retries,
                )
                self.total_errors += 1
                exhausted_results.extend(retry_batch)

            # Remove processed batch (whether success or failure)
            results_to_retry = results_to_retry[10:]

        return not exhausted_results

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
            "error_rate": self.total_errors
            / max(self.total_written + self.total_errors, 1),
            "queue_size": len(self.write_queue),
            "avg_write_time_seconds": avg_write_time,
            "throughput_per_second": throughput,
            "last_write_time": datetime.fromtimestamp(self.last_write_time).isoformat(),
            "write_enabled": self.config.db_write_enabled,
        }

    def get_health_status(self) -> dict[str, Any]:
        """Get database writer health status"""
        if not self.config.db_write_enabled:
            return {"status": "disabled", "reason": "write_disabled_in_config"}

        error_rate = self.total_errors / max(self.total_written + self.total_errors, 1)
        queue_usage = len(self.write_queue) / max(self.config.db_batch_size * 2, 1)

        if error_rate > 0.1:  # > 10% error rate
            return {
                "status": "unhealthy",
                "reason": "high_error_rate",
                "error_rate": error_rate,
            }
        if queue_usage > 0.8:  # Queue building up
            return {
                "status": "degraded",
                "reason": "queue_building_up",
                "queue_usage": queue_usage,
            }
        if not self._writer_task or self._writer_task.done():
            return {"status": "unhealthy", "reason": "writer_task_stopped"}
        return {
            "status": "healthy",
            "reason": "ok",
            "queue_size": len(self.write_queue),
            "error_rate": error_rate,
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


# Keep alias for backward compatibility
ensure_tables_exist = ensure_radar_metrics_tables
