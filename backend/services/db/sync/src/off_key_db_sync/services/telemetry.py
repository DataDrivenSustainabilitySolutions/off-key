import time

from datetime import datetime, timezone, timedelta
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
from off_key_core.utils.string import string_to_float
from off_key_core.utils.enum import HealthStatus
from ..config.config import get_sync_settings


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

        logger.info("event=telemetry_sync.initialized", extra=self._log_context)

        # Log active retention period (uses centralized config)
        retention_days = get_sync_settings().config.retention_days
        logger.info(
            "event=telemetry_sync.retention_window retention_days=%s",
            retention_days,
            extra={**self._log_context, "retention_days": retention_days},
        )

    async def _check_existing_data_coverage(
        self, charger_id: str, hierarchy_type: str
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        """
        Check the earliest and latest timestamps for existing telemetry data.

        Args:
            charger_id: The charger ID to check
            hierarchy_type: The telemetry hierarchy type

        Returns:
            Tuple of (earliest_timestamp, latest_timestamp)
            or (None, None) if no data exists
        """
        try:
            stmt = select(
                func.min(Telemetry.timestamp), func.max(Telemetry.timestamp)
            ).where(
                Telemetry.charger_id == charger_id, Telemetry.type == hierarchy_type
            )
            result = await self.session.execute(stmt)
            row = result.first()

            if row and row[0] is not None and row[1] is not None:
                logger.debug(
                    "event=telemetry_sync.coverage_found charger_id=%s \
                          hierarchy=%s start=%s end=%s",
                    charger_id,
                    hierarchy_type,
                    row[0],
                    row[1],
                )
                return row[0], row[1]
            else:
                logger.debug(
                    "event=telemetry_sync.coverage_missing charger_id=%s hierarchy=%s",
                    charger_id,
                    hierarchy_type,
                )
                return None, None

        except Exception as e:
            logger.error(
                "event=telemetry_sync.coverage_check_failed charger_id=%s \
                     hierarchy=%s error=%s",
                charger_id,
                hierarchy_type,
                e,
                exc_info=True,
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
            "event=telemetry_sync.started limit=%s",
            limit,
            extra={**self._log_context, "limit": limit},
        )
        try:
            stmt = select(Charger.charger_id)  # Select all charger IDs
            result = await self.session.execute(stmt)
            all_charger_ids = result.scalars().all()
        except Exception as e:
            logger.error(
                "event=telemetry_sync.query_chargers_failed error=%s",
                e,
                extra=self._log_context,
                exc_info=True,
            )
            self.total_syncs_failed += 1
            self.last_sync_status = "failed"
            self.last_sync_time = datetime.now()
            return

        if not all_charger_ids:
            logger.warning("event=telemetry_sync.no_chargers", extra=self._log_context)
            self.last_sync_status = "no_chargers"
            self.last_sync_time = datetime.now()
            return

        logger.info(
            "event=telemetry_sync.chargers_discovered count=%s", len(all_charger_ids)
        )
        log_ids_display = all_charger_ids[:5] + (
            ["..."] if len(all_charger_ids) > 5 else []
        )
        logger.debug("event=telemetry_sync.charger_sample sample=%s", log_ids_display)

        # 2. Date range calculation ('dr') removed.
        chargers_processed_count = 0

        # 3. Iterate through each charger found in the database
        for charger_id in all_charger_ids:
            chargers_processed_count += 1
            self.total_chargers_processed += 1
            logger.debug(
                "event=telemetry_sync.charger_processing charger_id=%s \
                     index=%s total=%s",
                charger_id,
                chargers_processed_count,
                len(all_charger_ids),
            )
            if chargers_processed_count % 25 == 0:
                logger.info(
                    "event=telemetry_sync.progress chargers_processed=%s \
                         total_chargers=%s",
                    chargers_processed_count,
                    len(all_charger_ids),
                )

            # 3a. Fetch Device Model to discover telemetry hierarchies
            logger.debug(
                "event=telemetry_sync.device_model_fetching charger_id=%s", charger_id
            )
            try:
                device_model = await self.client.get_device_info(charger_id)
                if not isinstance(device_model, dict):
                    logger.warning(
                        "event=telemetry_sync.device_model_invalid charger_id=%s",
                        charger_id,
                    )
                    continue
            except Exception as e:
                logger.error(
                    "event=telemetry_sync.device_model_fetch_failed \
                         charger_id=%s error=%s",
                    charger_id,
                    e,
                    exc_info=True,
                )
                continue

            telemetry_hierarchies = []
            for part in device_model.get("parts", []):
                if isinstance(part, dict):
                    for telemetry in part.get("telemetries", []):
                        if isinstance(telemetry, dict) and "hierarchy" in telemetry:
                            telemetry_hierarchies.append(telemetry["hierarchy"])

            if not telemetry_hierarchies:
                logger.warning(
                    "event=telemetry_sync.no_hierarchies charger_id=%s",
                    charger_id,
                )
                continue

            logger.debug(
                "event=telemetry_sync.hierarchies_discovered charger_id=%s count=%s",
                charger_id,
                len(telemetry_hierarchies),
            )

            # 3b. Iterate through each discovered hierarchy
            hierarchies_processed_count = 0
            for hierarchy_raw in telemetry_hierarchies:
                hierarchies_processed_count += 1
                self.total_hierarchies_processed += 1
                logger.debug(
                    "event=telemetry_sync.hierarchy_processing charger_id=%s \
                         hierarchy=%s index=%s total=%s",
                    charger_id,
                    hierarchy_raw,
                    hierarchies_processed_count,
                    len(telemetry_hierarchies),
                )

                # Use hierarchy directly (preserves slashes for MQTT topic matching)
                hierarchy_db_type = hierarchy_raw

                if not hierarchy_db_type:
                    logger.warning(
                        "event=telemetry_sync.hierarchy_empty charger_id=%s", charger_id
                    )
                    continue

                # Check for existing data coverage if gap detection is enabled
                config = get_sync_settings().config
                start_date = None
                end_date = None
                earliest = None
                latest = None
                now = datetime.now(timezone.utc).replace(tzinfo=None)

                # Calculate retention window
                window_start = now - timedelta(days=config.retention_days)

                if config.enable_gap_detection:
                    earliest, latest = await self._check_existing_data_coverage(
                        charger_id, hierarchy_db_type
                    )

                    if earliest and latest:
                        # Normalize to timezone-naive UTC for comparison
                        if earliest.tzinfo is not None:
                            earliest = earliest.astimezone(timezone.utc).replace(
                                tzinfo=None
                            )
                        if latest.tzinfo is not None:
                            latest = latest.astimezone(timezone.utc).replace(
                                tzinfo=None
                            )

                        # Check if latest data is within retention window
                        if latest >= window_start:
                            # Data is fresh enough for incremental sync
                            if config.enable_incremental_sync:
                                start_date = latest
                                end_date = now
                                logger.debug(
                                    "event=telemetry_sync.incremental charger_id=%s \
                                         hierarchy=%s start=%s end=%s",
                                    charger_id,
                                    hierarchy_raw,
                                    latest,
                                    now,
                                )
                            else:
                                logger.debug(
                                    "event=telemetry_sync.gap_detection_recent \
                                         charger_id=%s hierarchy=%s limit=%s",
                                    charger_id,
                                    hierarchy_raw,
                                    limit,
                                )
                        else:
                            # Latest data is too old, restart from retention window
                            start_date = window_start
                            end_date = now
                            logger.debug(
                                "event=telemetry_sync.gap_recovery charger_id=%s \
                                     hierarchy=%s latest=%s start=%s retention_days=%s",
                                charger_id,
                                hierarchy_raw,
                                latest,
                                start_date,
                                config.retention_days,
                            )
                    else:
                        # No existing data, fetch retention window
                        start_date = window_start
                        end_date = now
                        logger.debug(
                            "event=telemetry_sync.initial_sync charger_id=%s \
                                 hierarchy=%s start=%s retention_days=%s",
                            charger_id,
                            hierarchy_raw,
                            start_date,
                            config.retention_days,
                        )
                else:
                    logger.debug(
                        "event=telemetry_sync.fetch_without_gap_detection \
                             charger_id=%s hierarchy=%s limit=%s",
                        charger_id,
                        hierarchy_raw,
                        limit,
                    )

                # Fetch telemetry data with pagination support
                all_items = []
                pagination_calls = 0
                try:
                    telemetry_api_response = await self.client.get_telemetry_data(
                        charger_id, hierarchy_raw, limit, start_date, end_date
                    )
                    items = (
                        telemetry_api_response.get("items", [])
                        if isinstance(telemetry_api_response, dict)
                        else []
                    )
                    all_items.extend(items)

                    # Handle pagination if enabled and more data is available
                    remaining_count = (
                        telemetry_api_response.get("remainingCount", 0)
                        if isinstance(telemetry_api_response, dict)
                        else 0
                    )
                    total_count = (
                        telemetry_api_response.get("totalCount", 0)
                        if isinstance(telemetry_api_response, dict)
                        else 0
                    )

                    logger.debug(
                        "event=telemetry_sync.api_response charger_id=%s \
                             hierarchy=%s items=%s remaining=%s total=%s",
                        charger_id,
                        hierarchy_raw,
                        len(items),
                        remaining_count,
                        total_count,
                    )

                    if config.enable_pagination and remaining_count > 0:
                        logger.debug(
                            "event=telemetry_sync.pagination_pending charger_id=%s \
                                 hierarchy=%s remaining=%s",
                            charger_id,
                            hierarchy_raw,
                            remaining_count,
                        )

                        # Epsilon to advance cursor and prevent duplicate fetches
                        epsilon = timedelta(milliseconds=1)

                        # Iteratively fetch remaining data
                        while (
                            remaining_count > 0
                            and pagination_calls < config.max_pagination_calls
                        ):
                            pagination_calls += 1

                            # Use the last timestamp as the new start_date for next page
                            if all_items:
                                last_item = all_items[-1]
                                if (
                                    isinstance(last_item, dict)
                                    and "timestamp" in last_item
                                ):
                                    ts_str = unquote(last_item.get("timestamp", ""))
                                    if ts_str:
                                        if ts_str.endswith("Z"):
                                            next_start = datetime.fromisoformat(
                                                ts_str.replace("Z", "+00:00")
                                            ).replace(tzinfo=None)
                                        else:
                                            next_start = datetime.fromisoformat(ts_str)
                                            if next_start.tzinfo is None:
                                                next_start = next_start.replace(
                                                    tzinfo=timezone.utc
                                                )
                                            # Convert to UTC before making naive
                                            next_start = next_start.astimezone(
                                                timezone.utc
                                            ).replace(tzinfo=None)

                                        # Advance cursor to prevent duplicate fetches
                                        next_start = next_start + epsilon

                                        logger.debug(
                                            "event=telemetry_sync.pagination_call \
                                                 charger_id=%s hierarchy=%s \
                                                     call=%s start=%s",
                                            charger_id,
                                            hierarchy_raw,
                                            pagination_calls,
                                            next_start,
                                        )

                                        # Fetch next page
                                        next_response = (
                                            await self.client.get_telemetry_data(
                                                charger_id,
                                                hierarchy_raw,
                                                limit,
                                                next_start,
                                                end_date,
                                            )
                                        )
                                        next_items = (
                                            next_response.get("items", [])
                                            if isinstance(next_response, dict)
                                            else []
                                        )
                                        all_items.extend(next_items)

                                        remaining_count = (
                                            next_response.get("remainingCount", 0)
                                            if isinstance(next_response, dict)
                                            else 0
                                        )

                                        logger.debug(
                                            "event=telemetry_sync.pagination_result \
                                                 charger_id=%s hierarchy=%s call=%s \
                                                     items=%s remaining=%s",
                                            charger_id,
                                            hierarchy_raw,
                                            pagination_calls,
                                            len(next_items),
                                            remaining_count,
                                        )
                                    else:
                                        break
                            else:
                                break

                        if (
                            pagination_calls >= config.max_pagination_calls
                            and remaining_count > 0
                        ):
                            logger.warning(
                                "event=telemetry_sync.pagination_limit_reached \
                                     charger_id=%s hierarchy=%s \
                                         max_calls=%s remaining=%s",
                                charger_id,
                                hierarchy_raw,
                                config.max_pagination_calls,
                                remaining_count,
                            )
                        elif remaining_count == 0:
                            logger.debug(
                                "event=telemetry_sync.pagination_complete \
                                    charger_id=%s hierarchy=%s \
                                         total_items=%s calls=%s",
                                charger_id,
                                hierarchy_raw,
                                len(all_items),
                                pagination_calls + 1,
                            )

                except Exception as e:
                    logger.error(
                        "event=telemetry_sync.fetch_failed charger_id=%s \
                             hierarchy=%s error=%s",
                        charger_id,
                        hierarchy_raw,
                        e,
                        exc_info=True,
                    )
                    continue

                # Use all_items (which includes paginated results) instead of items
                items = all_items

                if not items:
                    logger.debug(
                        "event=telemetry_sync.no_items charger_id=%s \
                             hierarchy=%s",
                        charger_id,
                        hierarchy_raw,
                    )
                    continue

                # Log message reflects potentially large amount of data
                logger.debug(
                    "event=telemetry_sync.items_processing charger_id=%s \
                         hierarchy=%s items=%s",
                    charger_id,
                    hierarchy_raw,
                    len(items),
                )
                logger.debug(
                    "event=telemetry_sync.items_sample charger_id=%s \
                         hierarchy=%s sample=%s",
                    charger_id,
                    hierarchy_raw,
                    items[:3],
                )

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

                        # Skip records within existing coverage if gap detection om
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
                            "event=telemetry_sync.item_skipped charger_id=%s \
                                 hierarchy=%s index=%s total=%s error=%s",
                            charger_id,
                            hierarchy_raw,
                            items_processed_count,
                            len(items),
                            item_error,
                        )
                        continue

                if items_filtered_by_gap_detection > 0:
                    logger.debug(
                        "event=telemetry_sync.items_filtered_by_coverage charger_id=%s \
                             hierarchy=%s filtered=%s total=%s",
                        charger_id,
                        hierarchy_raw,
                        items_filtered_by_gap_detection,
                        len(items),
                    )
                if items_skipped_count > 0:
                    logger.warning(
                        "event=telemetry_sync.items_skipped charger_id=%s \
                             hierarchy=%s skipped=%s total=%s",
                        charger_id,
                        hierarchy_raw,
                        items_skipped_count,
                        len(items),
                    )
                if not telemetry_records_to_insert:
                    logger.debug(
                        "event=telemetry_sync.no_valid_records charger_id=%s \
                             hierarchy=%s items=%s",
                        charger_id,
                        hierarchy_raw,
                        len(items),
                    )
                    continue

                # 3d. Bulk insert valid records in batches using ON CONFLICT DO NOTHING
                logger.debug(
                    "event=telemetry_sync.insert_prepared charger_id=%s \
                         hierarchy=%s records=%s",
                    charger_id,
                    hierarchy_raw,
                    len(telemetry_records_to_insert),
                )

                # Dynamic batch size based on record count for better performance
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
                pending_batches = 0
                pending_records = 0

                # Execute all batches, then commit once at the end
                try:
                    for i in range(0, len(telemetry_records_to_insert), batch_size):
                        batch_num += 1
                        batch = telemetry_records_to_insert[i : i + batch_size]
                        logger.debug(
                            "event=telemetry_sync.batch_preparing charger_id=%s \
                                 hierarchy=%s batch=%s size=%s",
                            charger_id,
                            hierarchy_raw,
                            batch_num,
                            len(batch),
                        )
                        stmt = insert(Telemetry).values(batch)
                        stmt = stmt.on_conflict_do_nothing()
                        await self.session.execute(stmt)
                        pending_batches += 1
                        pending_records += len(batch)
                        logger.debug(
                            "event=telemetry_sync.batch_executed charger_id=%s \
                                 hierarchy=%s batch=%s",
                            charger_id,
                            hierarchy_raw,
                            batch_num,
                        )

                    # Commit once after all batches for this hierarchy
                    await self.session.commit()

                    # Only increment metrics after successful commit
                    successful_batches = pending_batches
                    self.total_batches_processed += pending_batches
                    self.total_records_inserted += pending_records

                    logger.debug(
                        "event=telemetry_sync.batches_committed charger_id=%s \
                             hierarchy=%s batches=%s records=%s",
                        charger_id,
                        hierarchy_raw,
                        batch_num,
                        pending_records,
                    )
                except IntegrityError as ie:
                    await self.session.rollback()
                    failed_batches = pending_batches
                    successful_batches = 0
                    self.total_batches_failed += failed_batches
                    logger.error(
                        "event=telemetry_sync.batch_integrity_error charger_id=%s \
                             hierarchy=%s pending_batches=%s error=%s",
                        charger_id,
                        hierarchy_raw,
                        pending_batches,
                        ie,
                        exc_info=True,
                    )
                except Exception as e:
                    await self.session.rollback()
                    failed_batches = pending_batches
                    successful_batches = 0
                    self.total_batches_failed += failed_batches
                    logger.error(
                        "event=telemetry_sync.batch_insert_failed charger_id=%s \
                             hierarchy=%s pending_batches=%s error=%s",
                        charger_id,
                        hierarchy_raw,
                        pending_batches,
                        e,
                        exc_info=True,
                    )

                logger.debug(
                    "event=telemetry_sync.batch_result charger_id=%s \
                         hierarchy=%s successful=%s failed=%s",
                    charger_id,
                    hierarchy_raw,
                    successful_batches,
                    failed_batches,
                )

            logger.debug(
                "event=telemetry_sync.charger_complete charger_id=%s hierarchies=%s",
                charger_id,
                hierarchies_processed_count,
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
            "event=telemetry_sync.completed chargers=%s \
                 hierarchies=%s records=%s batches_successful=%s \
                     batches_failed=%s latency_s=%.2f",
            chargers_processed_count,
            self.total_hierarchies_processed,
            self.total_records_inserted,
            self.total_batches_processed,
            self.total_batches_failed,
            sync_latency,
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
        config = get_sync_settings().config

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
