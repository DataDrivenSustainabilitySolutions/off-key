from datetime import datetime, timezone, timedelta

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from off_key.core.config import settings

from ..core.client.pionix import PionixClient
from ..core.logs import logger, log_performance
import time
from ..db.models import Charger


class ChargersSyncService:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session
        self.client = PionixClient(settings.PIONIX_KEY, settings.PIONIX_USER_AGENT)

    async def sync_chargers(self):
        """
        Synchronizes the db with the latest chargers as received from PIONIX Cloud.
        Adds chargers not present in the database.
        Updates information for chargers already present in the database.
        """
        start_time = time.time()
        logger.info("Starting charger synchronization")

        try:
            chargers_url = settings.build_pionix_url("chargers")
            active_chargers_data = await self.client.get(chargers_url)
            if not active_chargers_data:
                logger.warning("Received empty list of active chargers.")
                return  # Nothing to sync
        except Exception as e:
            logger.error(f"Failed to fetch active chargers: {e}")
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
            logger.info(
                f"Charger synchronization complete | "
                f"Total processed: {len(active_chargers_data)} | "
                f"Added: {len(chargers_to_add)} | "
                f"Updated: {chargers_updated_count}"
            )
            log_performance("charger_sync", start_time)
        except Exception as e:
            logger.error(f"Database commit failed during charger sync: {e}")
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
                    Charger.last_seen is not None,
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

                # Log success based on the operation performed
                if days_inactive == -1:
                    logger.info(f"Successfully deleted ALL {deleted_count} chargers.")
                else:
                    logger.info(
                        f"Successfully deleted {deleted_count} inactive chargers."
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
