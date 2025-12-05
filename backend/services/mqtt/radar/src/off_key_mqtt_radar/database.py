"""
Database writer for RADAR service

Handles batch writing of anomaly detection results to the database
with error handling and performance optimization.

Note: This module uses RADAR_DATABASE_URL environment variable directly
to avoid depending on off_key_core.db.base which requires the full Settings
class with 23+ environment variables.
"""

import asyncio
import os
import time
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from collections import deque

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert
from off_key_core.db.models import Anomaly

from .config import MQTTRadarConfig
from .models import ServiceMetrics, AnomalyResult

logger = logging.getLogger(__name__)

# Lazy-initialized async session factory
_radar_async_session_factory = None


def get_radar_async_session_factory():
    """
    Get or create async session factory using RADAR_DATABASE_URL env var.

    This allows radar containers to connect to the database without
    depending on off_key_core.db.base which requires the full Settings class.

    Raises ValueError if RADAR_DATABASE_URL is not set.
    """
    global _radar_async_session_factory

    if _radar_async_session_factory is None:
        database_url = os.getenv("RADAR_DATABASE_URL")
        if not database_url:
            raise ValueError(
                "RADAR_DATABASE_URL environment variable is required. "
                "For local development, add it to docker-compose.yml."
            )

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
        self.session_factory = session_factory or get_radar_async_session_factory()

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

        logger.info("Initialized database writer for RADAR service")

    async def start(self):
        """Start the database writer"""
        if not self.config.db_write_enabled:
            logger.info("Database writing disabled by configuration")
            return

        # Test database connection
        await self._test_connection()

        # Start writer task
        self._writer_task = asyncio.create_task(self._writer_loop())

        logger.info("Database writer started")

    async def stop(self):
        """Stop the database writer and flush remaining records"""
        logger.info("Stopping database writer")

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

        logger.info("Database writer stopped")

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
            logger.error(f"Failed to write service metrics: {e}")
            self.total_errors += 1

    async def _test_connection(self):
        """Test database connection"""
        try:
            async with self.session_factory() as session:
                # Simple test query
                result = await session.execute(text("SELECT 1"))
                result.fetchone()
                logger.info("Database connection test successful")
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            raise

    async def _writer_loop(self):
        """Main writer loop for batch processing"""
        logger.info("Started database writer loop")

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
            logger.info("Database writer loop cancelled")
        except Exception as e:
            logger.error(f"Database writer loop error: {e}")

        logger.info("Database writer loop stopped")

    def _extract_telemetry_type(self, topic: str) -> str:
        """Extract telemetry type from MQTT topic.

        Expected topic formats:
        - charger/{charger_id}/telemetry/{type}
        - charger/{charger_id}/{type}

        Args:
            topic: MQTT topic string

        Returns:
            Extracted telemetry type or "unknown" if extraction fails
        """
        if not topic:
            return "unknown"

        parts = topic.split("/")
        # Format: charger/{charger_id}/telemetry/{type}
        if len(parts) >= 4 and parts[2] == "telemetry":
            return parts[3]
        # Format: charger/{charger_id}/{type}
        if len(parts) >= 3 and parts[0] == "charger":
            return parts[2]
        return "unknown"

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
                    anomaly_records = [
                        {
                            "charger_id": result.charger_id or "unknown",
                            "timestamp": result.timestamp,
                            "telemetry_type": self._extract_telemetry_type(
                                result.topic
                            ),
                            "anomaly_type": "ml_detected",
                            "anomaly_value": result.anomaly_score,
                        }
                        for result in anomalies_to_write
                    ]

                    # Use INSERT ... ON CONFLICT DO NOTHING for idempotency
                    # (composite PK: charger_id, timestamp, telemetry_type)
                    stmt = pg_insert(Anomaly).values(anomaly_records)
                    stmt = stmt.on_conflict_do_nothing(
                        index_elements=["charger_id", "timestamp", "telemetry_type"]
                    )
                    await session.execute(stmt)
                    await session.commit()

                    logger.info(
                        f"Wrote {anomaly_count} anomalies to database "
                        f"(from batch of {batch_size} results)"
                    )

            # Update statistics
            write_time = time.time() - start_time
            self.write_times.append(write_time)
            self.total_written += anomaly_count
            self.last_write_time = time.time()

            # Clear the queue
            self.write_queue.clear()

        except Exception as e:
            logger.error(f"Failed to write batch of {anomaly_count} anomalies: {e}")
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
                        anomaly_records = [
                            {
                                "charger_id": result.charger_id or "unknown",
                                "timestamp": result.timestamp,
                                "telemetry_type": self._extract_telemetry_type(
                                    result.topic
                                ),
                                "anomaly_type": "ml_detected",
                                "anomaly_value": result.anomaly_score,
                            }
                            for result in retry_batch
                        ]

                        stmt = pg_insert(Anomaly).values(anomaly_records)
                        stmt = stmt.on_conflict_do_nothing(
                            index_elements=["charger_id", "timestamp", "telemetry_type"]
                        )
                        await session.execute(stmt)
                        await session.commit()

                        self.total_written += len(retry_batch)
                        logger.info(
                            f"Successfully retried writing {len(retry_batch)} anomalies"
                        )
                        success = True
                        break  # Exit retry loop on success

                except Exception as e:
                    logger.error(f"Retry attempt {attempt + 1} failed: {e}")
                    retry_delay *= 2  # Exponential backoff

            if not success:
                logger.error(
                    f"Dropping batch of {len(retry_batch)} anomalies "
                    f"after {max_retries} failed attempts"
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
                logger.info("Creating RADAR service metrics tables...")

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
                logger.info("RADAR service metrics tables created successfully")
            else:
                logger.info("RADAR service metrics tables already exist")

        logger.info("Database table verification completed")

    except Exception as e:
        logger.error(f"Failed to ensure RADAR metrics tables exist: {e}")
        logger.warning(
            "Continuing without table creation - "
            "metrics tables should be handled by migrations or manual setup"
        )


# Keep alias for backward compatibility
ensure_tables_exist = ensure_radar_metrics_tables
