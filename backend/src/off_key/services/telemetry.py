import logging

from datetime import datetime, timezone
from urllib.parse import unquote
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from off_key.core.config import settings

from ..core.client.pionix import PionixClient
from ..core.logs import logger
from ..db.models import Charger, Telemetry
from ..utils.string import clean_string, string_to_float

logging.getLogger("sqlalchemy.engine").setLevel(logging.CRITICAL)


class TelemetrySyncService:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session
        self.client = PionixClient(settings.PIONIX_KEY, settings.PIONIX_USER_AGENT)
        logger.info("TelemetrySyncService initialized (retention logic removed).")

    async def sync_telemetry(self, limit: int):
        """
        Synchronizes ALL available telemetry data for ALL known chargers.

        Fetches all historical telemetry for each hierarchy of every charger
        and inserts new records into the Telemetry table. Relies on database unique
        constraints (via ON CONFLICT DO NOTHING) to avoid duplication.
        WARNING: Fetching all data can be very resource-intensive.
        """

        # 1. Query ALL known charger IDs from the database
        logger.info("Querying all known charger IDs from the database...")
        try:
            stmt = select(Charger.charger_id)  # Select all charger IDs
            result = await self.session.execute(stmt)
            all_charger_ids = result.scalars().all()
        except Exception as e:
            logger.error(f"Failed to query charger IDs from database: {e}")
            return

        if not all_charger_ids:
            logger.warning("No chargers found in the database. Telemetry sync aborted.")
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
            logger.info(
                f"--- Processing Charger ID: {charger_id} "
                f"({chargers_processed_count}/{len(all_charger_ids)}) ---"
            )

            # 3a. Fetch Device Model to discover telemetry hierarchies
            dm_url = f"chargers/{charger_id}/deviceModel"
            logger.debug(f"Fetching device model: {dm_url}")
            try:
                device_model = await self.client.get(dm_url)
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
                logger.debug(
                    f"Processing hierarchy "
                    f"{hierarchies_processed_count}/{len(telemetry_hierarchies)}: "
                    f"'{hierarchy_raw}' for {charger_id}."
                )

                hierarchy_url_part = hierarchy_raw.replace("/", "%2F")
                hierarchy_db_type = clean_string(hierarchy_raw)

                if not hierarchy_db_type:
                    logger.warning(
                        f"Skipping hierarchy '{hierarchy_raw}' for {charger_id} "
                        f"due to cleaning returning None."
                    )
                    continue

                get_url = (
                    f"chargers/{charger_id}/"
                    f"telemetry/{hierarchy_url_part}?Limit={limit}"
                )
                logger.info(
                    f"Fetching ALL telemetry data points: {get_url}"
                )  # Log change

                try:
                    telemetry_api_response = await self.client.get(get_url)
                    items = (
                        telemetry_api_response.get("items", [])
                        if isinstance(telemetry_api_response, dict)
                        else []
                    )
                except Exception as e:
                    logger.error(f"Failed to fetch telemetry from {get_url}: {e}")
                    continue

                if not items:
                    logger.info(
                        f"No telemetry items retrieved for "
                        f"{charger_id} / {hierarchy_raw} from {get_url}"
                    )
                    continue

                # Log message reflects potentially large amount of data
                logger.info(
                    f"Retrieved {len(items)} items (potentially all historical) "
                    f"for {charger_id} / {hierarchy_raw}. "
                    f"Preparing for insertion."
                )
                logger.debug(f"First 3 items sample: {items[:3]}")

                # 3c. Process items and prepare records for database insertion
                telemetry_records_to_insert = []
                items_processed_count = 0
                items_skipped_count = 0
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
                        value_float = string_to_float(item.get("value"))
                        created_naive = datetime.now(timezone.utc).replace(tzinfo=None)
                        telemetry_records_to_insert.append(
                            {
                                "charger_id": charger_id,
                                "timestamp": timestamp_naive,
                                "value": value_float,
                                "type": hierarchy_db_type,
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
                record_count = len(telemetry_records_to_insert)
                if record_count < 1000:
                    batch_size = record_count  # Single batch for small datasets
                elif record_count < 10000:
                    batch_size = 2000  # Smaller batches for medium datasets
                else:
                    batch_size = 5000  # Larger batches for big datasets
                
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
                        logger.debug(
                            f"Committed batch {batch_num} for "
                            f"{charger_id} / {hierarchy_raw}."
                        )
                    except IntegrityError as ie:
                        await self.session.rollback()
                        failed_batches += 1
                        logger.error(
                            f"IntegrityError during batch {batch_num} insert for "
                            f"{charger_id}/{hierarchy_raw}: {ie}. "
                            f"Rolling back batch."
                        )
                    except Exception as e:
                        await self.session.rollback()
                        failed_batches += 1
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

        logger.info(
            f"Telemetry synchronization process completed. "
            f" {chargers_processed_count} chargers."
        )
