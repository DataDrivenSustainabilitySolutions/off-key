"""
Database Sync Service Orchestrator

Orchestrates database initialization and background synchronization.
Similar to MQTTProxyService pattern for consistent service architecture.
"""

import asyncio
import signal
from typing import Optional
from sqlalchemy import text

from off_key_core.config.logs import logger
from off_key_core.db.base import get_async_engine
from off_key_core.db.models import Base
from .config.config import get_sync_settings
from .services.background_sync import BackgroundSyncService


class SyncService:
    """
    Main Database Sync Service that orchestrates all components

    This service:
    1. Initializes database schema
    2. Manages background sync scheduler lifecycle
    3. Handles graceful shutdown
    4. Provides health status
    """

    def __init__(self):
        self.background_sync: Optional[BackgroundSyncService] = None
        self.is_running = False
        self.initial_sync_complete = False
        self.schema_ready = False
        self.shutdown_event = asyncio.Event()

        # Logging context
        self._log_context = {"component": "sync_service", "service": "db_sync"}

    async def _initialize_database(self) -> bool:
        """
        Initialize database by creating all tables.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info("Starting database initialization", extra=self._log_context)

            async with get_async_engine().begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
                await self._migrate_anomaly_identity(conn)
                await self._migrate_model_registry_family(conn)
                await conn.run_sync(Base.metadata.create_all)

            self.schema_ready = True
            logger.info("Database tables created successfully", extra=self._log_context)
            return True

        except Exception as e:
            self.schema_ready = False
            logger.error(
                f"Database initialization failed: {e}",
                extra=self._log_context,
                exc_info=True,
            )
            return False

    async def _migrate_model_registry_family(self, conn) -> None:
        """
        Ensure model_registry.family exists, is populated, and is non-null.

        This is a deterministic schema/data migration step for existing deployments
        where `model_registry` may predate the family column.
        """
        table_exists = await conn.scalar(
            text("SELECT to_regclass('public.model_registry') IS NOT NULL")
        )
        if not table_exists:
            return

        family_column_exists = await conn.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'model_registry'
                      AND column_name = 'family'
                )
                """
            )
        )
        if not family_column_exists:
            logger.info("Adding model_registry.family column", extra=self._log_context)
            await conn.execute(
                text("ALTER TABLE model_registry ADD COLUMN family TEXT")
            )

        # Backfill legacy rows for built-in registry entries.
        await conn.execute(
            text(
                """
                UPDATE model_registry
                SET family = CASE
                    WHEN model_type = 'knn' THEN 'distance'
                    WHEN model_type IN (
                        'isolation_forest',
                        'mondrian_forest'
                    ) THEN 'forest'
                    WHEN model_type = 'adaptive_svm' THEN 'svm'
                    WHEN model_type = 'standard_scaler' THEN 'scaling'
                    WHEN model_type = 'pca' THEN 'projection'
                    ELSE family
                END
                WHERE family IS NULL OR btrim(family) = ''
                """
            )
        )
        await conn.execute(
            text(
                """
                UPDATE model_registry
                SET family = lower(btrim(family))
                WHERE family IS NOT NULL
                """
            )
        )

        unresolved = (
            await conn.execute(
                text(
                    """
                    SELECT model_type, category
                    FROM model_registry
                    WHERE family IS NULL OR btrim(family) = ''
                    ORDER BY model_type
                    """
                )
            )
        ).all()
        if unresolved:
            unresolved_names = ", ".join(
                f"{model_type}({category})" for model_type, category in unresolved[:20]
            )
            raise RuntimeError(
                "Cannot finalize model_registry.family migration. "
                "Some entries still have no family. Update these rows manually: "
                f"{unresolved_names}"
            )

        # Enforce non-null after successful backfill.
        family_nullable = await conn.scalar(
            text(
                """
                SELECT is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'model_registry'
                  AND column_name = 'family'
                """
            )
        )
        if family_nullable == "YES":
            logger.info(
                "Enforcing NOT NULL on model_registry.family", extra=self._log_context
            )
            await conn.execute(
                text("ALTER TABLE model_registry ALTER COLUMN family SET NOT NULL")
            )

        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_model_registry_family "
                "ON model_registry (family)"
            )
        )

    async def _migrate_anomaly_identity(self, conn) -> None:
        """
        Maintain anomaly identity in dedicated table with strict uniqueness.

        Clean break:
        - `anomalies` hypertable stores only anomaly payload (time-series semantics).
        - `anomaly_identity` stores globally unique `anomaly_id` keyed to composite PK.
        """
        anomalies_exists = await conn.scalar(
            text("SELECT to_regclass('public.anomalies') IS NOT NULL")
        )
        if not anomalies_exists:
            return

        # `anomaly_identity.anomaly_id` is DB-generated to avoid app-side ID races.
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

        logger.info(
            "Normalizing anomalies schema before hypertable conversion",
            extra=self._log_context,
        )
        await conn.execute(text("DROP INDEX IF EXISTS idx_anomaly_id"))
        await conn.execute(
            text(
                "ALTER TABLE anomalies DROP CONSTRAINT \
                    IF EXISTS anomalies_anomaly_id_key"
            )
        )

        current_pk = await conn.execute(
            text(
                """
                SELECT
                    tc.constraint_name,
                    string_agg(
                        kcu.column_name,
                        ',' ORDER BY kcu.ordinal_position
                    ) AS columns
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = 'public'
                  AND tc.table_name = 'anomalies'
                  AND tc.constraint_type = 'PRIMARY KEY'
                GROUP BY tc.constraint_name
                """
            )
        )
        current_pk_row = current_pk.first()
        expected_pk_columns = "charger_id,timestamp,telemetry_type"
        if current_pk_row is not None and current_pk_row[1] != expected_pk_columns:
            logger.info(
                f"Dropping legacy anomalies PK ({current_pk_row[0]})",
                extra=self._log_context,
            )
            await conn.execute(
                text(
                    f'ALTER TABLE anomalies \
                        DROP CONSTRAINT IF EXISTS "{current_pk_row[0]}"'
                )
            )

        await conn.execute(
            text("ALTER TABLE anomalies DROP COLUMN IF EXISTS anomaly_id")
        )

        normalized_pk_columns = await conn.scalar(
            text(
                """
                SELECT string_agg(
                    kcu.column_name,
                    ',' ORDER BY kcu.ordinal_position
                )
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = 'public'
                  AND tc.table_name = 'anomalies'
                  AND tc.constraint_type = 'PRIMARY KEY'
                """
            )
        )
        if normalized_pk_columns != expected_pk_columns:
            logger.info(
                "Creating anomalies composite primary key "
                "(charger_id, timestamp, telemetry_type)",
                extra=self._log_context,
            )
            await conn.execute(
                text(
                    """
                    ALTER TABLE anomalies
                    ADD CONSTRAINT pk_anomaly
                    PRIMARY KEY (charger_id, timestamp, telemetry_type)
                    """
                )
            )

        anomalies_is_hypertable = await conn.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM timescaledb_information.hypertables
                    WHERE hypertable_schema = 'public'
                      AND hypertable_name = 'anomalies'
                )
                """
            )
        )
        if not anomalies_is_hypertable:
            logger.info(
                "Converting anomalies table to Timescale hypertable",
                extra=self._log_context,
            )
            await conn.execute(
                text(
                    """
                    SELECT create_hypertable(
                        'anomalies',
                        'timestamp',
                        if_not_exists => TRUE,
                        migrate_data => TRUE
                    )
                    """
                )
            )

        identity_exists = await conn.scalar(
            text("SELECT to_regclass('public.anomaly_identity') IS NOT NULL")
        )
        if not identity_exists:
            logger.info(
                "Creating anomaly_identity table",
                extra=self._log_context,
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE anomaly_identity (
                        anomaly_id TEXT PRIMARY KEY
                            DEFAULT gen_random_uuid()::text,
                        charger_id TEXT NOT NULL,
                        timestamp TIMESTAMPTZ NOT NULL,
                        telemetry_type TEXT NOT NULL,
                        created TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_anomaly_identity_target UNIQUE (
                            charger_id, timestamp, telemetry_type
                        ),
                        CONSTRAINT fk_anomaly_identity_anomaly
                            FOREIGN KEY (charger_id, timestamp, telemetry_type)
                            REFERENCES anomalies (charger_id, timestamp, telemetry_type)
                            ON DELETE CASCADE
                    )
                    """
                )
            )
        else:
            await conn.execute(
                text(
                    """
                    ALTER TABLE anomaly_identity
                    ALTER COLUMN anomaly_id
                    SET DEFAULT gen_random_uuid()::text
                    """
                )
            )

        await conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'uq_anomaly_identity_target'
                          AND conrelid = 'anomaly_identity'::regclass
                    ) THEN
                        ALTER TABLE anomaly_identity
                        ADD CONSTRAINT uq_anomaly_identity_target
                        UNIQUE (charger_id, timestamp, telemetry_type);
                    END IF;
                END
                $$;
                """
            )
        )
        await conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'fk_anomaly_identity_anomaly'
                          AND conrelid = 'anomaly_identity'::regclass
                    ) THEN
                        ALTER TABLE anomaly_identity
                        ADD CONSTRAINT fk_anomaly_identity_anomaly
                        FOREIGN KEY (charger_id, timestamp, telemetry_type)
                        REFERENCES anomalies (charger_id, timestamp, telemetry_type)
                        ON DELETE CASCADE;
                    END IF;
                END
                $$;
                """
            )
        )

        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_anomaly_identity_charger_timestamp "
                "ON anomaly_identity (charger_id, timestamp)"
            )
        )

        # Backfill missing identity rows; IDs are generated by DB default.
        await conn.execute(
            text(
                """
                INSERT INTO anomaly_identity (
                    charger_id, timestamp, telemetry_type
                )
                SELECT
                    a.charger_id,
                    a.timestamp,
                    a.telemetry_type
                FROM anomalies AS a
                LEFT JOIN anomaly_identity AS ai
                  ON ai.charger_id = a.charger_id
                 AND ai.timestamp = a.timestamp
                 AND ai.telemetry_type = a.telemetry_type
                WHERE ai.anomaly_id IS NULL
                """
            )
        )

    async def _check_database_connection(self) -> bool:
        """
        Check if database connection is available.

        Returns:
            bool: True if connection is successful, False otherwise
        """
        try:
            async with get_async_engine().begin() as conn:
                await conn.execute(text("SELECT 1"))
            return True

        except Exception as e:
            logger.error(
                f"Database connection failed: {e}",
                extra=self._log_context,
                exc_info=True,
            )
            return False

    def _on_initial_sync_complete(self):
        """Callback when initial sync completes"""
        self.initial_sync_complete = True
        logger.info("Initial sync marked as complete", extra=self._log_context)

    async def _wait_for_database(self, max_retries: int = 30, delay: int = 2) -> bool:
        """
        Wait for database to become available.

        Args:
            max_retries: Maximum number of connection attempts
            delay: Delay between attempts in seconds

        Returns:
            bool: True if database becomes available, False if max retries exceeded
        """
        for attempt in range(1, max_retries + 1):
            logger.info(
                f"Database connection attempt {attempt}/{max_retries}",
                extra=self._log_context,
            )

            if await self._check_database_connection():
                logger.info("Database connection successful", extra=self._log_context)
                return True

            if attempt < max_retries:
                logger.info(
                    f"Waiting {delay} seconds before next attempt",
                    extra=self._log_context,
                )
                await asyncio.sleep(delay)

        logger.error(
            f"Database not available after {max_retries} attempts",
            extra=self._log_context,
        )
        return False

    async def start(self):
        """Start the database sync service"""
        config = get_sync_settings().config
        if self.is_running:
            logger.warning(
                "Database sync service already running", extra=self._log_context
            )
            return

        logger.info("Starting database sync service", extra=self._log_context)

        try:
            # Wait for database to be available
            if not await self._wait_for_database():
                raise RuntimeError("Database not available")

            # Initialize database
            if not await self._initialize_database():
                raise RuntimeError("Database initialization failed")

            # API source sync jobs are removed; fail fast on unsupported mode.
            if not config.enabled:
                logger.info(
                    "Background sync disabled",
                    extra={**self._log_context, "sync_enabled": False},
                )
                self.initial_sync_complete = True
            elif config.source_mode == "mqtt_only":
                logger.info(
                    "SYNC_SOURCE_MODE=mqtt_only: skipping API sync jobs",
                    extra={**self._log_context, "source_mode": config.source_mode},
                )
                # In MQTT-only mode there is no initial cloud sync phase.
                self.initial_sync_complete = True
            else:
                raise RuntimeError(
                    "SYNC_SOURCE_MODE=api is not supported because API adapters were "
                    "removed. Use SYNC_SOURCE_MODE=mqtt_only."
                )

            self.is_running = True

            logger.info(
                "Database sync service started successfully", extra=self._log_context
            )

        except Exception as e:
            logger.error(
                f"Failed to start database sync service: {e}",
                extra=self._log_context,
                exc_info=True,
            )

            # Cleanup on failure
            await self.stop()
            raise

    async def stop(self):
        """Stop the database sync service"""
        if not self.is_running:
            logger.info(
                "Database sync service already stopped", extra=self._log_context
            )
            return

        logger.info("Stopping database sync service", extra=self._log_context)
        shutdown_start_time = asyncio.get_event_loop().time()

        # Signal shutdown
        self.shutdown_event.set()
        self.is_running = False
        self.schema_ready = False

        try:
            # Stop background sync if running
            if self.background_sync:
                await self.background_sync.stop()
                logger.info(
                    "Background sync scheduler stopped", extra=self._log_context
                )

            shutdown_duration = asyncio.get_event_loop().time() - shutdown_start_time

            logger.info(
                f"Database sync service stopped successfully in "
                f"{shutdown_duration:.2f}s",
                extra={**self._log_context, "shutdown_duration": shutdown_duration},
            )

        except Exception as e:
            logger.error(
                f"Error during database sync service shutdown: {e}",
                extra=self._log_context,
                exc_info=True,
            )
            raise

    async def run(self):
        """Run the database sync service"""

        # Set up signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            logger.info(
                f"Received signal {signum}, initiating graceful shutdown",
                extra=self._log_context,
            )
            asyncio.create_task(self.stop())

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            # Start the service
            await self.start()

            # Keep running until shutdown signal
            logger.info(
                "Database sync service running, waiting for shutdown signal",
                extra=self._log_context,
            )
            await self.shutdown_event.wait()

        except Exception as e:
            logger.error(
                f"Unexpected error in database sync service: {e}",
                extra=self._log_context,
                exc_info=True,
            )

        finally:
            # Ensure cleanup
            await self.stop()

    def get_health_status(self):
        """Get current health status"""
        config = get_sync_settings().config
        # Service is only healthy if running, schema is ready,
        # and initial sync completed.
        is_healthy = (
            self.is_running and self.schema_ready and self.initial_sync_complete
        )

        status = {
            "status": (
                "healthy"
                if is_healthy
                else ("starting" if self.is_running else "stopped")
            ),
            "sync_enabled": config.enabled,
            "source_mode": config.source_mode,
            "schema_ready": self.schema_ready,
            "initial_sync_complete": self.initial_sync_complete,
            "components": {},
        }

        if self.background_sync:
            status["components"]["background_sync"] = self.background_sync.get_status()

        return status

    def get_background_sync_service(self) -> Optional[BackgroundSyncService]:
        """Get background sync service instance for API access"""
        return self.background_sync
