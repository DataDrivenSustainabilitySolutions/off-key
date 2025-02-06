from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.core.client.pionix import PionixClient
from backend.app.core.config import settings
from backend.app.db.models import Chargers


class ChargersSyncService:
    def __init__(self, db: Session):
        self.db: Session = db
        self.client = PionixClient(settings.PIONIX_KEY, settings.PIONIX_USER_AGENT)

    async def sync_chargers(self):
        active_chargers = await self.client.get("api/chargers")

        # Extract active charger IDs
        active_ids = {charger["id"] for charger in active_chargers}

        # Fetch all known chargers from the database
        known_chargers = self.db.execute(select(Chargers)).scalars().all()
        existing_ids = {charger.charger_id for charger in known_chargers}

        # Identify new and inactive chargers
        new_ids = active_ids - existing_ids
        inactive_ids = existing_ids - active_ids

        # Insert new chargers
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
        self.db.add_all(new_chargers)

        # Deactivate chargers not in the provided list
        if inactive_ids:
            self.db.execute(
                update(Chargers)
                .where(Chargers.charger_id.in_(inactive_ids))
                .values(is_active=False)
            )

        # Commit changes
        self.db.commit()
