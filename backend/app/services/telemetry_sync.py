from datetime import datetime, timezone, timedelta
from urllib.parse import quote, unquote
from xmlrpc.client import DateTime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import cast, DateTime
from sqlalchemy.dialects.postgresql import insert

from ..core.client.pionix import PionixClient
from ..core.config import settings
from ..core.logs import logger
from ..db.models import Chargers, Telemetry
from ..utils.strings import clean_string


class TelemetrySyncService:
    def __init__(self, session: Session, retention_days: int = 14):
        self.session: Session = session
        self.client = PionixClient(settings.PIONIX_KEY, settings.PIONIX_USER_AGENT)

        self.retention_days = retention_days

    async def sync_telemetry(self):

        two_weeks_ago = datetime.now(timezone.utc) - timedelta(weeks=2)

        # Query all charger_id where online is True
        online_charger_ids = (
            self.session.query(Chargers.charger_id).filter(Chargers.online, cast(Chargers.last_seen, DateTime) >= two_weeks_ago).all()
        )
        online_charger_ids = [charger_id[0] for charger_id in online_charger_ids]

        logger.info(
            f"Synchronization Charger IDs: {online_charger_ids}"
        )

        dr = self._get_date_range()
        for charger_id in online_charger_ids:

            dm_url = f"api/chargers/{charger_id}/deviceModel"
            logger.info(f"Fetching {dm_url}")

            try:
                device_model = await self.client.get(dm_url)
            except Exception as e:
                logger.error(f"Failed to fetch {dm_url}: {e}")
                continue

            # Extract telemetries' hierarchy values
            telemetry_hierarchies = [
                telemetry["hierarchy"]
                for part in device_model.get("parts", [])
                for telemetry in part.get("telemetries", [])
            ]

            logger.info(f"Extracted Hierarchies: {telemetry_hierarchies}")

            for hierarchy in telemetry_hierarchies:
                logger.info(f"Telemetries: {hierarchy} ({charger_id}).")

                hierarchy = hierarchy.replace("/", "%2F")
                get_url = f"api/chargers/{charger_id}/telemetry/{hierarchy}{dr}&Limit=1000000"

                logger.info(f"Request URL: {get_url}")

                telemetry = await self.client.get(get_url)
                items = telemetry.get("items", [])

                if not items:
                    logger.warning(f"No data retrieved from {get_url}")
                    continue  # No data to insert

                logger.info(f"Preparing database entries for {get_url}")
                telemetry_records = [
                    {
                        "charger_id": charger_id,
                        "timestamp": datetime.fromisoformat(
                            unquote(item["timestamp"]).replace("Z", "+00:00")
                        ),
                        "value": (
                            float(item["value"]) if item["value"] != "string" else None
                        ),
                        "type": clean_string(hierarchy),
                        "created": datetime.now(timezone.utc),
                    }
                    for item in items
                ]

                logger.info("Starting to bulk insert telemetry entries")

                try:
                    stmt = insert(Telemetry).values(telemetry_records)
                    stmt = stmt.on_conflict_do_nothing()  # Skip rows that violate unique constraints
                    self.session.execute(stmt)
                    self.session.commit()
                except IntegrityError:
                    self.session.rollback()
                    # Log the error or handle it as needed
                    print("IntegrityError encountered during bulk insert.")


    def _get_date_range(self):

        # Get current UTC time
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=self.retention_days)

        # Format as ISO 8601 string with 'Z' for UTC
        now_iso_ts = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-3] + "Z"
        past_iso_ts = past.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-3] + "Z"

        # URL encode the timestamps
        return "?StartDate=" + quote(past_iso_ts) + "&EndDate=" + quote(now_iso_ts)
