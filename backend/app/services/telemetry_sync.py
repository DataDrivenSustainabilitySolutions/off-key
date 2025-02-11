from sqlalchemy.orm import Session

from ..core.client.pionix import PionixClient
from ..core.config import settings
from ..db.models import Chargers


class TelemetrySyncService:
    def __init__(self, session: Session):
        self.session: Session = session
        self.client = PionixClient(settings.PIONIX_KEY, settings.PIONIX_USER_AGENT)

    async def sync_telemetry(self):

        # Query all charger_id where online is True
        online_charger_ids = self.session.query(Chargers.charger_id).filter(Chargers.online is True).all()
        online_charger_ids = [c[0] for c in online_charger_ids]

        # Close session
        self.session.close()