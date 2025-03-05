from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.client.pionix import PionixClient
from ..core.config import settings
from ..core.logs import logger
from ..db.models import Chargers, Telemetry


class ChargersSyncService:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session
        self.client = PionixClient(settings.PIONIX_KEY, settings.PIONIX_USER_AGENT)

    async def sync_chargers(self):
        active_chargers = await self.client.get("api/chargers")

        # Extract active charger IDs
        active_ids = {charger["id"] for charger in active_chargers}

        # Fetch all known chargers from the database
        result = await self.session.execute(select(Chargers))
        known_chargers = result.scalars().all()
        existing_ids = {charger.charger_id for charger in known_chargers}

        # Identify new and inactive chargers
        new_ids = active_ids - existing_ids
        inactive_ids = existing_ids - active_ids
        logger.info(f"Inactive chargers found: {inactive_ids}")

        new_chargers = [
            Chargers(
                charger_id=charger["id"],
                manufacturer_name=charger.get("manufacturerName"),
                charger_name=charger.get("chargerName"),
                firmware_version=charger.get("firmwareVersion"),
                last_seen=charger.get("lastSeen"),
                state=charger.get("state"),
                online=charger.get("online", True),
            )
            for charger in active_chargers
            if charger["id"] in new_ids
        ]
        self.session.add_all(new_chargers)

        # Deactivate chargers not in the provided list
        if inactive_ids:
            logger.info("Initiating clean-up for inactive charger IDs.")

            # Flag inactive chargers
            await self.session.execute(
                update(Chargers)
                .where(Chargers.charger_id.in_(inactive_ids))
                .values(online=False)
            )

            # Delete telemetry data for inactive chargers
            await self.session.execute(
                delete(Telemetry).where(Telemetry.charger_id.in_(inactive_ids))
            )

        # Delete charges data for inactive chargers
        await self.session.execute(delete(Chargers).where(Chargers.online.is_(False)))

        # Commit changes
        await self.session.commit()  # Use await to commit asynchronously
