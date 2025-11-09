"""
Database writer for RADAR service

Handles batch writing of anomaly detection results to the database
with error handling and performance optimization.
"""

import asyncio
import time
from datetime import datetime
from typing import List, Optional, Dict, Any
from collections import deque

from sqlalchemy import text
from off_key_core.config.logs import logger
from off_key_core.db.base import AsyncSessionLocal

from .config.config import MQTTRadarConfig
from .models import ServiceMetrics, AnomalyResult, Base


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
        self.session_factory = session_factory or AsyncSessionLocal

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

    async def _flush_batch(self):
        """Flush current batch to database"""
        if not self.write_queue:
            return

        batch_size = len(self.write_queue)
        start_time = time.time()

        try:
            async with self.session_factory() as session:
                # Convert results to database records
                db_records = []
                for result in self.write_queue:
                    db_record = result.to_db_record(
                        model_type="radar_model",  # Could be made configurable
                        model_version="1.0",
                    )
                    db_records.append(db_record)

                # Batch insert
                session.add_all(db_records)
                await session.commit()

                # Update statistics
                write_time = time.time() - start_time
                self.write_times.append(write_time)
                self.total_written += batch_size
                self.last_write_time = time.time()

                logger.info(
                    f"Wrote batch of {batch_size} anomaly records in {write_time:.3f}s"
                )

                # Clear the queue
                self.write_queue.clear()

        except Exception as e:
            logger.error(f"Failed to write batch of {batch_size} records: {e}")
            self.total_errors += 1

            # Implement retry logic
            await self._retry_failed_batch()

    async def _retry_failed_batch(self):
        """Retry writing failed batch with exponential backoff"""
        max_retries = 3
        retry_delay = 1.0

        for attempt in range(max_retries):
            try:
                await asyncio.sleep(retry_delay)

                async with self.session_factory() as session:
                    # Try to write a subset of records
                    retry_batch = self.write_queue[:10]  # Limit retry batch size

                    db_records = []
                    for result in retry_batch:
                        db_record = result.to_db_record("radar_model", "1.0")
                        db_records.append(db_record)

                    session.add_all(db_records)
                    await session.commit()

                    # Remove successfully written records
                    self.write_queue = self.write_queue[10:]
                    self.total_written += len(retry_batch)

                    logger.info(
                        f"Successfully retried writing {len(retry_batch)} records"
                    )
                    return

            except Exception as e:
                logger.error(f"Retry attempt {attempt + 1} failed: {e}")
                retry_delay *= 2  # Exponential backoff

        # If all retries failed, drop the batch to prevent memory issues
        logger.error(
            f"Dropping failed batch of "
            f"{len(self.write_queue)} records after {max_retries} attempts"
        )
        self.write_queue.clear()
        self.total_errors += 1

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


async def ensure_tables_exist():
    """Ensure database tables exist (for development/testing)"""
    try:
        async with AsyncSessionLocal() as session:
            # Try to create tables using raw SQL first
            try:
                # Check if radar_anomalies table exists
                result = await session.execute(
                    text("SELECT to_regclass('radar_anomalies')")
                )
                table_exists = result.scalar() is not None

                if not table_exists:
                    # TODO: DIRTY! THIS MUST BE DONE SOMEWHERE ELSE...
                    logger.info("RADAR tables don't exist, creating them...")

                    # Create radar_anomalies table
                    await session.execute(
                        text(
                            """
                        CREATE TABLE IF NOT EXISTS radar_anomalies (
                            id SERIAL PRIMARY KEY,
                            topic VARCHAR(255) NOT NULL,
                            charger_id VARCHAR(100),
                            anomaly_score FLOAT NOT NULL,
                            severity VARCHAR(20) NOT NULL,
                            is_anomaly BOOLEAN NOT NULL DEFAULT FALSE,
                            raw_data JSONB NOT NULL,
                            processed_features JSONB,
                            model_type VARCHAR(50) NOT NULL,
                            model_version VARCHAR(50),
                            message_timestamp TIMESTAMP,
                            processed_timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
                            context JSONB,
                            notes TEXT
                        )
                    """
                        )
                    )

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

                    # Create indexes for better performance
                    await session.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS "
                            "idx_radar_anomalies_topic "
                            "ON radar_anomalies(topic)"
                        )
                    )
                    await session.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS "
                            "idx_radar_anomalies_charger_id "
                            "ON radar_anomalies(charger_id)"
                        )
                    )
                    await session.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS "
                            "idx_radar_anomalies_severity "
                            "ON radar_anomalies(severity)"
                        )
                    )
                    await session.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS "
                            "idx_radar_anomalies_is_anomaly "
                            "ON radar_anomalies(is_anomaly)"
                        )
                    )
                    await session.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS "
                            "idx_radar_anomalies_score "
                            "ON radar_anomalies(anomaly_score)"
                        )
                    )
                    await session.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS "
                            "idx_radar_service_metrics_timestamp "
                            "ON radar_service_metrics(timestamp)"
                        )
                    )

                    await session.commit()
                    logger.info("RADAR database tables created successfully")
                else:
                    logger.info("RADAR database tables already exist")

            except Exception as sql_error:
                logger.warning(f"Raw SQL table creation failed: {sql_error}")

                # Fallback: Try using SQLAlchemy metadata (might work with some engines)
                try:
                    engine = session.get_bind()

                    # For async engines, use run_sync
                    if hasattr(engine, "run_sync"):
                        await engine.run_sync(Base.metadata.create_all)
                        logger.info("Tables created using SQLAlchemy metadata (async)")
                    else:
                        # Last resort - this might not work but we'll try
                        Base.metadata.create_all(bind=engine)
                        logger.info("Tables created using SQLAlchemy metadata (sync)")

                except Exception as metadata_error:
                    logger.error(
                        f"SQLAlchemy metadata creation also failed: {metadata_error}"
                    )
                    logger.warning(
                        "Could not create tables automatically."
                        " Please create them manually or via migrations."
                    )

        logger.info("Database table verification completed")

    except Exception as e:
        logger.error(f"Failed to ensure database tables exist: {e}")
        logger.warning(
            "Continuing without table creation -"
            " tables should be handled by migrations or manual setup"
        )
