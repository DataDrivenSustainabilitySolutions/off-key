from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from off_key_core.clients.base_client import ChargerAPIClient
from off_key_core.config.logs import logger, log_performance
from off_key_core.utils.enum import HealthStatus
import time
from off_key_core.db.models import Charger
from ..config.config import get_sync_settings


@dataclass
class ChargerSyncMetrics:
    """Charger synchronization performance metrics"""

    total_syncs_executed: int
    total_syncs_successful: int
    total_syncs_failed: int
    total_chargers_added: int
    total_chargers_updated: int
    total_chargers_cleaned: int
    sync_success_rate: float
    average_sync_latency: float
    last_sync_time: Optional[str]
    last_sync_status: str


@dataclass
class ChargerSyncHealthStatus:
    """Charger synchronization health status"""

    status: HealthStatus
    health_score: float
    performance: ChargerSyncMetrics


class ChargersSyncService:
    def __init__(self, session: AsyncSession, client: ChargerAPIClient):
        self.session: AsyncSession = session
        self.client = client

        # Performance metrics
        self.total_syncs_executed = 0
        self.total_syncs_successful = 0
        self.total_syncs_failed = 0
        self.total_chargers_added = 0
        self.total_chargers_updated = 0
        self.total_chargers_cleaned = 0
        self.sync_latency_sum = 0.0
        self.sync_latency_count = 0
        self.last_sync_time: Optional[datetime] = None
        self.last_sync_status = "never_run"

        # Logging context
        self._log_context = {"component": "charger_sync", "service": "db_sync"}

    async def sync_chargers(self):
        """
        Synchronizes the db with the latest chargers from an external API source.
        Adds chargers not present in the database.
        Updates information for chargers already present in the database.
        """
        start_time = time.time()
        self.total_syncs_executed += 1

        logger.info("Starting charger synchronization", extra=self._log_context)

        try:
            active_chargers_data = await self.client.get_chargers()
            if not active_chargers_data:
                logger.warning(
                    "Received empty list of active chargers.", extra=self._log_context
                )
                self.last_sync_status = "no_data"
                self.last_sync_time = datetime.now()
                return  # Nothing to sync
        except Exception as e:
            logger.error(
                f"Failed to fetch active chargers: {e}",
                extra=self._log_context,
                exc_info=True,
            )
            self.total_syncs_failed += 1
            self.last_sync_status = "failed"
            self.last_sync_time = datetime.now()
            return  # Cannot proceed without active chargers data

        active_chargers_map = {
            charger["id"]: charger for charger in active_chargers_data
        }
        active_ids = set(active_chargers_map.keys())

        # Fetch existing chargers from the database
        result = await self.session.execute(
            select(Charger).where(Charger.charger_id.in_(active_ids))
        )

        # Create a map of existing charger IDs to their DB objects for quick lookup
        existing_chargers_map = {ch.charger_id: ch for ch in result.scalars().all()}
        existing_ids = set(existing_chargers_map.keys())

        chargers_to_add = []
        chargers_updated_count = 0

        # Process each active charger
        for charger_id, charger_data in active_chargers_map.items():
            if charger_id in existing_ids:
                # --- Update existing charger ---
                db_charger = existing_chargers_map[charger_id]
                # Update attributes if they have changed
                db_charger.manufacturer_name = charger_data.get("certOrganization")
                db_charger.charger_name = charger_data.get("customName")
                db_charger.firmware_version = charger_data.get("firmwareVersion")
                db_charger.last_seen = charger_data.get("lastSeen")
                db_charger.state = str(charger_data.get("state"))
                db_charger.online = charger_data.get("online", True)
                chargers_updated_count += 1
                logger.debug(f"Updating charger ID: {charger_id}")
            else:
                # --- Add new charger ---
                new_charger = Charger(
                    charger_id=charger_id,
                    manufacturer_name=charger_data.get("certOrganization"),
                    charger_name=charger_data.get("customName"),
                    firmware_version=charger_data.get("firmwareVersion"),
                    last_seen=charger_data.get("lastSeen"),
                    state=str(charger_data.get("state")),
                    online=charger_data.get("online", True),
                )
                chargers_to_add.append(new_charger)
                logger.debug(f"Preparing to add new charger ID: {charger_id}")

        # Add all new chargers to the session
        if chargers_to_add:
            self.session.add_all(chargers_to_add)
            logger.info(f"Added {len(chargers_to_add)} new chargers.")

        if chargers_updated_count > 0:
            logger.info(f"Updated {chargers_updated_count} existing chargers.")

        # Commit additions and updates
        try:
            await self.session.commit()

            # Update metrics
            self.total_syncs_successful += 1
            self.total_chargers_added += len(chargers_to_add)
            self.total_chargers_updated += chargers_updated_count
            self.last_sync_status = "success"
            self.last_sync_time = datetime.now()

            # Track latency
            sync_latency = time.time() - start_time
            self.sync_latency_sum += sync_latency
            self.sync_latency_count += 1

            logger.info(
                f"Charger synchronization complete | "
                f"Total processed: {len(active_chargers_data)} | "
                f"Added: {len(chargers_to_add)} | "
                f"Updated: {chargers_updated_count} | "
                f"Latency: {sync_latency:.2f}s",
                extra={
                    **self._log_context,
                    "total_processed": len(active_chargers_data),
                    "added": len(chargers_to_add),
                    "updated": chargers_updated_count,
                    "latency": sync_latency,
                },
            )
            log_performance("charger_sync", start_time)
        except Exception as e:
            logger.error(
                f"Database commit failed during charger sync: {e}",
                extra=self._log_context,
                exc_info=True,
            )
            self.total_syncs_failed += 1
            self.last_sync_status = "failed"
            self.last_sync_time = datetime.now()
            await self.session.rollback()  # Rollback changes on error

    async def clean_chargers(self, days_inactive: int):
        """
        Removes chargers based on inactivity or deletes all if days_inactive is -1.

        - If days_inactive is a positive integer, removes chargers whose 'last_seen'
          timestamp (stored as a string) is older than that number of days.
        - If days_inactive is -1, removes ALL chargers regardless of 'last_seen'.

        Args:
            days_inactive: The maximum number of days since a charger was last seen,
                           or -1 to delete all chargers.
        """
        delete_statement = None  # Initialize delete_statement

        if days_inactive == -1:
            # --- Special case: Delete all chargers ---
            logger.warning(
                "Received days_inactive=-1. Preparing to delete ALL chargers."
            )
            # Delete statement targeting the Charger table without any conditions
            delete_statement = delete(Charger)

        elif days_inactive > 0:
            # --- Standard case: Delete chargers older than X days ---
            logger.info(
                f"Received days_inactive={days_inactive}. "
                f"Preparing to delete chargers older than {days_inactive} days."
            )
            try:
                cutoff_datetime = datetime.now(timezone.utc) - timedelta(
                    days=days_inactive
                )
                logger.info(
                    f"Cleaning chargers last seen before {cutoff_datetime.isoformat()}."
                )

                # Convert cutoff datetime to ISO string format for efficient comparison
                # This avoids expensive CAST operations and can use string indexes
                cutoff_iso_string = cutoff_datetime.isoformat()

                # Use string comparison which is much more efficient than casting
                delete_statement = delete(Charger).where(
                    Charger.last_seen.is_not(None),
                    Charger.last_seen < cutoff_iso_string,
                )
            except Exception as e:
                # Handle potential errors during date calculation itself
                logger.error(f"Error calculating cutoff date: {e}")
                return  # Cannot proceed if date calculation fails

        else:
            # --- Invalid input ---
            logger.error(
                f"Invalid input for charger cleaning: "
                f"days_inactive must be a positive integer or -1, got {days_inactive}"
            )
            return  # Exit if input is not valid

        # --- Proceed only if a valid delete statement was prepared ---
        if delete_statement is not None:
            try:
                # --- Execute the delete operation ---
                result = await self.session.execute(delete_statement)
                deleted_count = result.rowcount  # Get the number of rows affected

                # --- Commit the changes ---
                await self.session.commit()

                # Update metrics
                self.total_chargers_cleaned += deleted_count

                # Log success based on the operation performed
                if days_inactive == -1:
                    logger.info(
                        f"Successfully deleted ALL {deleted_count} chargers.",
                        extra={**self._log_context, "deleted_count": deleted_count},
                    )
                else:
                    logger.info(
                        f"Successfully deleted {deleted_count} inactive chargers.",
                        extra={
                            **self._log_context,
                            "deleted_count": deleted_count,
                            "days_inactive": days_inactive,
                        },
                    )

            except Exception as e:
                # Log the specific error, providing context
                log_context = (
                    "deleting all chargers"
                    if days_inactive == -1
                    else "cleaning inactive chargers (using string casting)"
                )
                logger.error(f"Failed during {log_context}: {e}")
                # Rollback changes on error
                await self.session.rollback()
        else:
            logger.error(
                "Delete statement was not correctly prepared. No action taken."
            )

    def get_performance_metrics(self) -> ChargerSyncMetrics:
        """Get performance metrics"""
        avg_latency = 0.0
        if self.sync_latency_count > 0:
            avg_latency = self.sync_latency_sum / self.sync_latency_count

        success_rate = 100.0
        if self.total_syncs_executed > 0:
            success_rate = (
                self.total_syncs_successful / self.total_syncs_executed
            ) * 100

        return ChargerSyncMetrics(
            total_syncs_executed=self.total_syncs_executed,
            total_syncs_successful=self.total_syncs_successful,
            total_syncs_failed=self.total_syncs_failed,
            total_chargers_added=self.total_chargers_added,
            total_chargers_updated=self.total_chargers_updated,
            total_chargers_cleaned=self.total_chargers_cleaned,
            sync_success_rate=round(success_rate, 2),
            average_sync_latency=round(avg_latency, 3),
            last_sync_time=(
                self.last_sync_time.isoformat() if self.last_sync_time else None
            ),
            last_sync_status=self.last_sync_status,
        )

    def get_health_status(self) -> ChargerSyncHealthStatus:
        """Get health status for monitoring"""
        metrics = self.get_performance_metrics()
        config = get_sync_settings().config

        # Determine health status
        status = HealthStatus.HEALTHY
        health_score = 100.0

        # Check for failures
        if metrics.sync_success_rate < config.charger_sync_success_rate_unhealthy:
            status = HealthStatus.UNHEALTHY
            health_score = metrics.sync_success_rate
        elif metrics.sync_success_rate < config.charger_sync_success_rate_degraded:
            status = HealthStatus.DEGRADED
            health_score = metrics.sync_success_rate

        # Check for high latency
        if metrics.average_sync_latency > config.charger_sync_latency_unhealthy:
            status = HealthStatus.UNHEALTHY
            health_score = min(health_score, 50.0)
        elif metrics.average_sync_latency > config.charger_sync_latency_degraded:
            if status == HealthStatus.HEALTHY:
                status = HealthStatus.DEGRADED
            health_score = min(health_score, 80.0)

        return ChargerSyncHealthStatus(
            status=status,
            health_score=round(health_score, 2),
            performance=metrics,
        )
