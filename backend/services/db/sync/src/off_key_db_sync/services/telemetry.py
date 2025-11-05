import logging
import time

from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from off_key_core.clients.base_client import ChargerAPIClient
from off_key_core.config.logs import logger
from off_key_core.db.models import Charger, Telemetry
from off_key_core.utils.string import clean_string, string_to_float
from off_key_core.utils.enum import HealthStatus
from ..config import sync_settings

logging.getLogger("sqlalchemy.engine").setLevel(logging.CRITICAL)


@dataclass
class TelemetrySyncMetrics:
    """Telemetry synchronization performance metrics"""

    total_syncs_executed: int
    total_syncs_successful: int
    total_syncs_failed: int
    total_chargers_processed: int
    total_hierarchies_processed: int
    total_records_inserted: int
    total_batches_processed: int
    total_batches_failed: int
    sync_success_rate: float
    batch_success_rate: float
    average_sync_latency: float
    last_sync_time: Optional[str]
    last_sync_status: str


@dataclass
class TelemetrySyncHealthStatus:
    """Telemetry synchronization health status"""

    status: HealthStatus
    health_score: float
    performance: TelemetrySyncMetrics


class TelemetrySyncService:
    def __init__(self, session: AsyncSession, client: ChargerAPIClient):
        self.session: AsyncSession = session
        self.client = client

        # Performance metrics
        self.total_syncs_executed = 0
        self.total_syncs_successful = 0
        self.total_syncs_failed = 0
        self.total_chargers_processed = 0
        self.total_hierarchies_processed = 0
        self.total_records_inserted = 0
        self.total_batches_processed = 0
        self.total_batches_failed = 0
        self.sync_latency_sum = 0.0
        self.sync_latency_count = 0
        self.last_sync_time: Optional[datetime] = None
        self.last_sync_status = "never_run"

        # Logging context
        self._log_context = {"component": "telemetry_sync", "service": "db_sync"}

        logger.info("TelemetrySyncService initialized", extra=self._log_context)


    async def _check_existing_data_coverage(
        self, charger_id: str, hierarchy_type: str
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        """
        Check the earliest and latest timestamps for existing telemetry data.

        Args:
            charger_id: The charger ID to check
            hierarchy_type: The telemetry hierarchy type

        Returns:
            Tuple of (earliest_timestamp, latest_timestamp) or (None, None) if no data exists
        """
        try:
            stmt = select(
                func.min(Telemetry.timestamp),
                func.max(Telemetry.timestamp)
            ).where(
                Telemetry.charger_id == charger_id,
                Telemetry.type == hierarchy_type
            )
            result = await self.session.execute(stmt)
            row = result.first()
            
            if row and row[0] is not None and row[1] is not None:
                logger.debug(
                    f"Existing data for {charger_id}/{hierarchy_type}: "
                    f"{row[0]} to {row[1]}"
                )
                return row[0], row[1]
            else:
                logger.debug(
                    f"No existing data for {charger_id}/{hierarchy_type}"
                )
                return None, None

        except Exception as e:
            logger.error(
                f"Failed to check existing data coverage for "
                f"{charger_id}/{hierarchy_type}: {e}"
            )
            return None, None

    async def sync_telemetry(self, limit: int):
        """
        Synchronizes ALL available telemetry data for ALL known chargers.

        Fetches all historical telemetry for each hierarchy of every charger
        and inserts new records into the Telemetry table. Relies on database unique
        constraints (via ON CONFLICT DO NOTHING) to avoid duplication.
        WARNING: Fetching all data can be very resource-intensive.
        """
        start_time = time.time()
        self.total_syncs_executed += 1

        # 1. Query ALL known charger IDs from the database
        logger.info(
            "Starting telemetry synchronization",
            extra={**self._log_context, "limit": limit},
        )
        try:
            stmt = select(Charger.charger_id)  # Select all charger IDs
            result = await self.session.execute(stmt)
            all_charger_ids = result.scalars().all()
        except Exception as e:
            logger.error(
                f"Failed to query charger IDs from database: {e}",
                extra=self._log_context,
                exc_info=True,
            )
            self.total_syncs_failed += 1
            self.last_sync_status = "failed"
            self.last_sync_time = datetime.now()
            return

        if not all_charger_ids:
            logger.warning(
                "No chargers found in the database. Telemetry sync aborted.",
                extra=self._log_context,
            )
            self.last_sync_status = "no_chargers"
            self.last_sync_time = datetime.now()
            return

        logger.info(f"Found {len(all_charger_ids)} chargers to sync telemetry for.")
        log_ids_display = all_charger_ids[:5] + (
            ["..."] if len(all_charger_ids) > 5 else []
        )
        logger.debug(f"Charger IDs sample: {log_ids_display}")

        # 2. Date range calculation ('dr') removed.
        chargers_processed_count = 0

        # 3. Iterate through each charger found in the database
        for charger_id in all_charger_ids:
            chargers_processed_count += 1
            self.total_chargers_processed += 1
            logger.info(
                f"--- Processing Charger ID: {charger_id} "
                f"({chargers_processed_count}/{len(all_charger_ids)}) ---"
            )

            # 3a. Fetch Device Model to discover telemetry hierarchies
            logger.debug(f"Fetching device model for charger: {charger_id}")
            try:
                device_model = await self.client.get_device_info(charger_id)
                if not isinstance(device_model, dict):
                    logger.warning(
                        f"Received unexpected device model format for {charger_id}. "
                        f"Skipping."
                    )
                    continue
            except Exception as e:
                logger.error(f"Failed to fetch device model for {charger_id}: {e}")
                continue

            telemetry_hierarchies = []
            for part in device_model.get("parts", []):
                if isinstance(part, dict):
                    for telemetry in part.get("telemetries", []):
                        if isinstance(telemetry, dict) and "hierarchy" in telemetry:
                            telemetry_hierarchies.append(telemetry["hierarchy"])

            if not telemetry_hierarchies:
                logger.warning(
                    f"No telemetry hierarchies found or "
                    f"extracted for charger {charger_id}."
                )
                continue

            logger.debug(f"Found hierarchies for {charger_id}: {telemetry_hierarchies}")

            # 3b. Iterate through each discovered hierarchy
            hierarchies_processed_count = 0
            for hierarchy_raw in telemetry_hierarchies:
                hierarchies_processed_count += 1
                self.total_hierarchies_processed += 1
                logger.debug(
                    f"Processing hierarchy "
                    f"{hierarchies_processed_count}/{len(telemetry_hierarchies)}: "
                    f"'{hierarchy_raw}' for {charger_id}."
                )

                hierarchy_db_type = clean_string(hierarchy_raw)

                if not hierarchy_db_type:
                    logger.warning(
                        f"Skipping hierarchy '{hierarchy_raw}' for {charger_id} "
                        f"due to cleaning returning None."
                    )
                    continue

                # Check for existing data coverage if gap detection is enabled
                config = sync_settings.config
                if config.enable_gap_detection:
                    earliest, latest = await self._check_existing_data_coverage(
                        charger_id, hierarchy_db_type
                    )
                    if earliest and latest:
                        logger.info(
                            f"Gap detection: Found existing data for "
                            f"{charger_id}/{hierarchy_raw} from {earliest} to {latest}. "
                            f"Fetching up to {limit} most recent records to check for updates."
                        )
                    else:
                        logger.info(
                            f"Gap detection: No existing data for {charger_id}/{hierarchy_raw}. "
                            f"Fetching up to {limit} records."
                        )
                else:
                    logger.info(
                        f"Fetching up to {limit} telemetry data points for "
                        f"{charger_id}/{hierarchy_raw} (gap detection disabled)"
                    )

                try:
                    telemetry_api_response = await self.client.get_telemetry_data(
                        charger_id, hierarchy_raw, limit
                    )
                    items = (
                        telemetry_api_response.get("items", [])
                        if isinstance(telemetry_api_response, dict)
                        else []
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to fetch telemetry for "
                        f"{charger_id}/{hierarchy_raw}: {e}"
                    )
                    continue

                if not items:
                    logger.info(
                        f"No telemetry items retrieved for "
                        f"{charger_id} / {hierarchy_raw}"
                    )
                    continue

                # Log message reflects potentially large amount of data
                logger.info(
                    f"Retrieved {len(items)} items for {charger_id} / {hierarchy_raw}. "
                    f"Preparing for insertion."
                )
                logger.debug(f"First 3 items sample: {items[:3]}")

                # 3c. Process items and prepare records for database insertion
                telemetry_records_to_insert = []
                items_processed_count = 0
                items_skipped_count = 0
                items_filtered_by_gap_detection = 0
                for item in items:
                    items_processed_count += 1
                    if not isinstance(item, dict):
                        items_skipped_count += 1
                        continue
                    try:
                        ts_str = unquote(item.get("timestamp", ""))
                        if not ts_str:
                            raise ValueError("Missing timestamp")
                        if ts_str.endswith("Z"):
                            ts_aware = datetime.fromisoformat(
                                ts_str.replace("Z", "+00:00")
                            )
                        else:
                            ts_aware = datetime.fromisoformat(ts_str)
                            if (
                                ts_aware.tzinfo is None
                                or ts_aware.tzinfo.utcoffset(ts_aware) is None
                            ):
                                ts_aware = ts_aware.replace(tzinfo=timezone.utc)
                        timestamp_naive = ts_aware.replace(tzinfo=None)
                        
                        # Skip records within existing coverage if gap detection is enabled
                        if config.enable_gap_detection and earliest and latest:
                            if earliest <= timestamp_naive <= latest:
                                items_filtered_by_gap_detection += 1
                                continue
                        
                        value_float = string_to_float(item.get("value"))
                        created_naive = datetime.now(timezone.utc).replace(tzinfo=None)
                        telemetry_records_to_insert.append(
                            {
                                "charger_id": charger_id,
                                "timestamp": timestamp_naive,
                                "value": value_float,
                                "type": hierarchy_db_type,
                                "data_source": "api_sync",
                                "created": created_naive,
                            }
                        )
                    except (KeyError, ValueError, TypeError) as item_error:
                        items_skipped_count += 1
                        logger.warning(
                            f"Skipping item {items_processed_count}/{len(items)} "
                            f"for {charger_id}/{hierarchy_raw} "
                            f"due to processing error: {item_error}. Item data: {item}"
                        )
                        continue

                if items_filtered_by_gap_detection > 0:
                    logger.info(
                        f"Gap detection: Filtered {items_filtered_by_gap_detection}/{len(items)} items "
                        f"for {charger_id}/{hierarchy_raw} (already in database coverage)."
                    )
                if items_skipped_count > 0:
                    logger.warning(
                        f"Skipped {items_skipped_count}/{len(items)} items "
                        f"for {charger_id}/{hierarchy_raw} "
                        f"due to processing errors."
                    )
                if not telemetry_records_to_insert:
                    logger.info(
                        f"No valid records to insert for {charger_id} / "
                        f"{hierarchy_raw} after processing {len(items)} items."
                    )
                    continue

                # 3d. Bulk insert valid records in batches using ON CONFLICT DO NOTHING
                logger.info(
                    f"Inserting {len(telemetry_records_to_insert)} processed "
                    f"records for {charger_id} / {hierarchy_raw}."
                )

                # Dynamic batch size based on record count for better performance
                config = sync_settings.config
                record_count = len(telemetry_records_to_insert)
                if record_count < config.batch_size_small:
                    batch_size = record_count  # Single batch for small datasets
                elif record_count < (config.batch_size_small * 10):
                    batch_size = (
                        config.batch_size_medium
                    )  # Smaller batches for medium datasets
                else:
                    batch_size = (
                        config.batch_size_large
                    )  # Larger batches for big datasets

                batch_num = 0
                successful_batches = 0
                failed_batches = 0

                for i in range(0, len(telemetry_records_to_insert), batch_size):
                    batch_num += 1
                    batch = telemetry_records_to_insert[i : i + batch_size]
                    logger.debug(
                        f"Preparing batch {batch_num} ({len(batch)} records) for "
                        f"{charger_id} / {hierarchy_raw}."
                    )
                    try:
                        stmt = insert(Telemetry).values(batch)
                        stmt = stmt.on_conflict_do_nothing()
                        result = await self.session.execute(stmt)
                        await self.session.commit()
                        successful_batches += 1
                        self.total_batches_processed += 1
                        self.total_records_inserted += len(batch)
                        logger.debug(
                            f"Committed batch {batch_num} for "
                            f"{charger_id} / {hierarchy_raw}."
                        )
                    except IntegrityError as ie:
                        await self.session.rollback()
                        failed_batches += 1
                        self.total_batches_failed += 1
                        logger.error(
                            f"IntegrityError during batch {batch_num} insert for "
                            f"{charger_id}/{hierarchy_raw}: {ie}. "
                            f"Rolling back batch."
                        )
                    except Exception as e:
                        await self.session.rollback()
                        failed_batches += 1
                        self.total_batches_failed += 1
                        logger.error(
                            f"Error during batch {batch_num} insert for "
                            f"{charger_id}/{hierarchy_raw}: {e}. "
                            f"Rolling back batch."
                        )

                logger.info(
                    f"Batch processing completed for {charger_id}/{hierarchy_raw}: "
                    f"{successful_batches} successful, {failed_batches} failed"
                )

            logger.info(
                f"Finished processing {hierarchies_processed_count} hierarchies "
                f"for Charger ID: {charger_id}."
            )

        # Update final metrics
        self.total_syncs_successful += 1
        self.last_sync_status = "success"
        self.last_sync_time = datetime.now()

        # Track latency
        sync_latency = time.time() - start_time
        self.sync_latency_sum += sync_latency
        self.sync_latency_count += 1

        logger.info(
            f"Telemetry synchronization completed | "
            f"Chargers: {chargers_processed_count} | "
            f"Hierarchies: {self.total_hierarchies_processed} | "
            f"Records: {self.total_records_inserted} | "
            f"Batches: {self.total_batches_processed} successful, "
            f"{self.total_batches_failed} failed | "
            f"Latency: {sync_latency:.2f}s",
            extra={
                **self._log_context,
                "chargers_processed": chargers_processed_count,
                "hierarchies_processed": self.total_hierarchies_processed,
                "records_inserted": self.total_records_inserted,
                "batches_successful": self.total_batches_processed,
                "batches_failed": self.total_batches_failed,
                "latency": sync_latency,
            },
        )

    def get_performance_metrics(self) -> TelemetrySyncMetrics:
        """Get performance metrics"""
        avg_latency = 0.0
        if self.sync_latency_count > 0:
            avg_latency = self.sync_latency_sum / self.sync_latency_count

        sync_success_rate = 100.0
        if self.total_syncs_executed > 0:
            sync_success_rate = (
                self.total_syncs_successful / self.total_syncs_executed
            ) * 100

        batch_success_rate = 100.0
        total_batches = self.total_batches_processed + self.total_batches_failed
        if total_batches > 0:
            batch_success_rate = (self.total_batches_processed / total_batches) * 100

        return TelemetrySyncMetrics(
            total_syncs_executed=self.total_syncs_executed,
            total_syncs_successful=self.total_syncs_successful,
            total_syncs_failed=self.total_syncs_failed,
            total_chargers_processed=self.total_chargers_processed,
            total_hierarchies_processed=self.total_hierarchies_processed,
            total_records_inserted=self.total_records_inserted,
            total_batches_processed=self.total_batches_processed,
            total_batches_failed=self.total_batches_failed,
            sync_success_rate=round(sync_success_rate, 2),
            batch_success_rate=round(batch_success_rate, 2),
            average_sync_latency=round(avg_latency, 3),
            last_sync_time=(
                self.last_sync_time.isoformat() if self.last_sync_time else None
            ),
            last_sync_status=self.last_sync_status,
        )

    def get_health_status(self) -> TelemetrySyncHealthStatus:
        """Get health status for monitoring"""
        metrics = self.get_performance_metrics()
        config = sync_settings.config

        # Determine health status
        status = HealthStatus.HEALTHY
        health_score = 100.0

        # Check for sync failures
        if metrics.sync_success_rate < config.telemetry_sync_success_rate_unhealthy:
            status = HealthStatus.UNHEALTHY
            health_score = metrics.sync_success_rate
        elif metrics.sync_success_rate < config.telemetry_sync_success_rate_degraded:
            status = HealthStatus.DEGRADED
            health_score = metrics.sync_success_rate

        # Check for batch failures
        if metrics.batch_success_rate < config.telemetry_batch_success_rate_unhealthy:
            status = HealthStatus.UNHEALTHY
            health_score = min(health_score, metrics.batch_success_rate)
        elif metrics.batch_success_rate < config.telemetry_batch_success_rate_degraded:
            if status == HealthStatus.HEALTHY:
                status = HealthStatus.DEGRADED
            health_score = min(health_score, metrics.batch_success_rate)

        # Check for high latency (telemetry sync takes longer)
        if metrics.average_sync_latency > config.telemetry_sync_latency_unhealthy:
            status = HealthStatus.UNHEALTHY
            health_score = min(health_score, 50.0)
        elif metrics.average_sync_latency > config.telemetry_sync_latency_degraded:
            if status == HealthStatus.HEALTHY:
                status = HealthStatus.DEGRADED
            health_score = min(health_score, 80.0)

        return TelemetrySyncHealthStatus(
            status=status,
            health_score=round(health_score, 2),
            performance=metrics,
        )
