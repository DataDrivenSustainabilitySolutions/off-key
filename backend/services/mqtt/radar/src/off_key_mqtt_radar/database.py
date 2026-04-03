"""
Database writer for RADAR service

Handles batch writing of anomaly detection results to the database
with error handling and performance optimization.

Note: This module uses RADAR_DATABASE_URL environment variable directly
to avoid depending on off_key_core.db.base which requires the full Settings
class with 23+ environment variables.
"""

import asyncio
import time
import logging
import math
from datetime import datetime
from typing import List, Optional, Dict, Any
from collections import deque

from sqlalchemy import Table, Column, Text, Float, TIMESTAMP, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import MetaData
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert

from off_key_core.utils.mqtt_topics import TopicMetadataExtractor
from .config.config import MQTTRadarConfig
from .config.runtime import get_radar_database_settings
from .models import ServiceMetrics, AnomalyResult

logger = logging.getLogger(__name__)
MULTIVARIATE_TELEMETRY_TYPE = "__multivariate__"

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
        self.write_queue: List[AnomalyResult] = []
        self.last_write_time = time.time()

        # Performance tracking
        self.total_written = 0
        self.total_errors = 0
        self.write_times = deque(maxlen=100)

        # Control
        self._writer_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        logger.info("event=radar.db_writer_initialized")

    async def start(self):
        """Start the database writer"""
        if not self.config.db_write_enabled:
            logger.debug("event=radar.db_writer_disabled")
            return

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

        # Cancel writer task
        if self._writer_task:
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass

        # Flush remaining records
        if self.write_queue:
            await self._flush_batch()

        logger.info("event=radar.db_writer_stopped")

    async def write_anomaly(self, result: AnomalyResult):
        """Queue anomaly result for batch writing"""
        if not self.config.db_write_enabled:
            return

        self.write_queue.append(result)

        # Check if we should flush batch
        if (
            len(self.write_queue) >= self.config.db_batch_size
            or (time.time() - self.last_write_time) > self.config.db_batch_timeout
        ):
            await self._flush_batch()

    async def write_service_metrics(self, metrics: Dict[str, Any]):
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
                await session.commit()

        except Exception as e:
            logger.error(
                "event=radar.db_metrics_write_failed error=%s",
                str(e),
                exc_info=True,
            )
            self.total_errors += 1

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
                except asyncio.TimeoutError:
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
        self, topic: str, payload: Optional[Dict[str, Any]] = None
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
    def _derive_anomaly_type(result: AnomalyResult) -> str:
        """Map detector output to stored anomaly semantics."""
        alignment_context = (result.context or {}).get("alignment", {})
        if bool(alignment_context.get("aligned_vector")):
            return "ml_tailprob_multivariate"
        return "ml_tailprob_univariate"

    @staticmethod
    def _derive_anomaly_value(result: AnomalyResult) -> float:
        """Persist tail probability when available to match trigger semantics."""
        score_window = (result.context or {}).get("score_window", {})
        tail_pvalue = score_window.get("tail_pvalue")
        if isinstance(tail_pvalue, (int, float)):
            tail_pvalue = float(tail_pvalue)
            if math.isfinite(tail_pvalue):
                return tail_pvalue
        return float(result.anomaly_score)

    async def _flush_batch(self):
        """Flush current batch to core anomalies table"""
        if not self.write_queue:
            return

        # Only write actual anomalies (is_anomaly=True)
        anomalies_to_write = [r for r in self.write_queue if r.is_anomaly]
        batch_size = len(self.write_queue)
        anomaly_count = len(anomalies_to_write)
        start_time = time.time()

        try:
            if anomalies_to_write:
                async with self.session_factory() as session:
                    # Convert results to core Anomaly records
                    anomaly_records = []
                    for result in anomalies_to_write:
                        anomaly_records.append(
                            {
                                "charger_id": result.charger_id or "unknown",
                                "timestamp": result.timestamp,
                                "telemetry_type": self._derive_telemetry_type(result),
                                "anomaly_type": self._derive_anomaly_type(result),
                                "anomaly_value": self._derive_anomaly_value(result),
                                "value_type": "tail_pvalue",
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

                    # Use INSERT ... ON CONFLICT DO NOTHING for idempotency
                    # (composite PK: charger_id, timestamp, telemetry_type)
                    stmt = pg_insert(ANOMALY_TABLE).values(anomaly_records)
                    stmt = stmt.on_conflict_do_nothing(
                        index_elements=["charger_id", "timestamp", "telemetry_type"]
                    )
                    await session.execute(stmt)

                    identity_stmt = pg_insert(ANOMALY_IDENTITY_TABLE).values(
                        identity_records
                    )
                    identity_stmt = identity_stmt.on_conflict_do_nothing(
                        index_elements=["charger_id", "timestamp", "telemetry_type"]
                    )
                    await session.execute(identity_stmt)
                    await session.commit()

                    logger.info(
                        "event=radar.db_batch_written anomaly_count=%s batch_size=%s",
                        anomaly_count,
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
            self.last_write_time = time.time()

            # Clear the queue
            self.write_queue.clear()

        except Exception as e:
            logger.error(
                "event=radar.db_batch_write_failed anomaly_count=%s error=%s",
                anomaly_count,
                str(e),
                exc_info=True,
            )
            self.total_errors += 1

            # Implement retry logic
            await self._retry_failed_batch()

    async def _retry_failed_batch(self):
        """Retry writing failed batch with exponential backoff.

        Processes anomalies in chunks of 10, retrying each chunk up to
        max_retries times before moving to the next chunk.
        """
        max_retries = 3
        base_delay = 1.0

        # Only retry actual anomalies
        anomalies_to_retry = [r for r in self.write_queue if r.is_anomaly]
        self.write_queue.clear()  # Clear queue immediately to prevent double processing

        if not anomalies_to_retry:
            return

        # Process in chunks of 10
        while anomalies_to_retry:
            retry_batch = anomalies_to_retry[:10]
            retry_delay = base_delay
            success = False

            for attempt in range(max_retries):
                try:
                    await asyncio.sleep(retry_delay)

                    async with self.session_factory() as session:
                        anomaly_records = []
                        for result in retry_batch:
                            anomaly_records.append(
                                {
                                    "charger_id": result.charger_id or "unknown",
                                    "timestamp": result.timestamp,
                                    "telemetry_type": self._derive_telemetry_type(
                                        result
                                    ),
                                    "anomaly_type": self._derive_anomaly_type(result),
                                    "anomaly_value": self._derive_anomaly_value(result),
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

                        stmt = pg_insert(ANOMALY_TABLE).values(anomaly_records)
                        stmt = stmt.on_conflict_do_nothing(
                            index_elements=["charger_id", "timestamp", "telemetry_type"]
                        )
                        await session.execute(stmt)

                        identity_stmt = pg_insert(ANOMALY_IDENTITY_TABLE).values(
                            identity_records
                        )
                        identity_stmt = identity_stmt.on_conflict_do_nothing(
                            index_elements=[
                                "charger_id",
                                "timestamp",
                                "telemetry_type",
                            ]
                        )
                        await session.execute(identity_stmt)
                        await session.commit()

                        self.total_written += len(retry_batch)
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
                    "event=radar.db_retry_exhausted dropped_count=%s max_retries=%s",
                    len(retry_batch),
                    max_retries,
                )
                self.total_errors += 1

            # Remove processed batch (whether success or failure)
            anomalies_to_retry = anomalies_to_retry[10:]

    def get_performance_metrics(self) -> Dict[str, Any]:
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
            "total_errors": self.total_errors,
            "error_rate": self.total_errors
            / max(self.total_written + self.total_errors, 1),
            "queue_size": len(self.write_queue),
            "avg_write_time_seconds": avg_write_time,
            "throughput_per_second": throughput,
            "last_write_time": datetime.fromtimestamp(self.last_write_time).isoformat(),
            "write_enabled": self.config.db_write_enabled,
        }

    def get_health_status(self) -> Dict[str, Any]:
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
        elif queue_usage > 0.8:  # Queue building up
            return {
                "status": "degraded",
                "reason": "queue_building_up",
                "queue_usage": queue_usage,
            }
        elif not self._writer_task or self._writer_task.done():
            return {"status": "unhealthy", "reason": "writer_task_stopped"}
        else:
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

                await session.commit()
                logger.info("event=radar.db_metrics_tables_created")
            else:
                logger.debug("event=radar.db_metrics_tables_exist")

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
