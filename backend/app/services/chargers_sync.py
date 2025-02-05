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

        # Fetch all known charger IDs
        known_chargers = self.db.execute(select(Chargers)).scalars().all()
        existing_ids = {charger.charger_id for charger in known_chargers}

        # Identify new and inactive chargers
        new_ids = set(active_chargers) - existing_ids
        inactive_ids = existing_ids - set(active_chargers)

        # Insert new chargers
        for charger_id in new_ids:
            new_charger = Chargers(
                charger_id=charger_id,
                is_active=True,
            )
            self.db.add(new_charger)

            # Deactivate chargers not in the provided list
            if inactive_ids:
                self.db.execute(
                    update(Chargers)
                    .where(Chargers.charger_id.in_(inactive_ids))
                    .values(is_active=False)
                )

            # Commit changes
            self.db.commit()
