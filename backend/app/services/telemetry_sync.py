from datetime import datetime, timezone, timedelta
from urllib.parse import quote, unquote
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, cast, DateTime
from sqlalchemy.dialects.postgresql import insert

from ..core.client.pionix import PionixClient
from ..core.config import settings
from ..core.logs import logger
from ..db.models import Chargers, Telemetry
from ..utils.strings import clean_string


class TelemetrySyncService:
    def __init__(self, session: AsyncSession, retention_days: int = 14):
        self.session: AsyncSession = session
        self.client = PionixClient(settings.PIONIX_KEY, settings.PIONIX_USER_AGENT)
        self.retention_days = retention_days

    async def sync_telemetry(self):
        # Strip timezone from the datetime
        two_weeks_ago = (datetime.now(timezone.utc) - timedelta(weeks=2)).replace(tzinfo=None)

        # Query all charger_id where online is True
        stmt = (
            select(Chargers.charger_id)
            .where(Chargers.online, cast(Chargers.last_seen, DateTime) >= two_weeks_ago)
        )
        result = await self.session.execute(stmt)
        online_charger_ids = result.scalars().all()

        logger.info(f"Synchronization Charger IDs: {online_charger_ids}")

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
                get_url = (
                    f"api/chargers/{charger_id}/telemetry/{hierarchy}{dr}&Limit=1000000"
                )

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
                        ).replace(tzinfo=None),  # Strip timezone for consistency
                        "value": (
                            float(item["value"]) if item["value"] != "string" else None
                        ),
                        "type": clean_string(hierarchy),
                        "created": datetime.now(timezone.utc).replace(tzinfo=None),  # Strip timezone
                    }
                    for item in items
                ]

                logger.info("Starting to bulk insert telemetry entries")

                try:
                    stmt = insert(Telemetry).values(telemetry_records)
                    stmt = stmt.on_conflict_do_nothing()  # Skip rows that violate unique constraints
                    await self.session.execute(stmt)
                    await self.session.commit()
                except IntegrityError:
                    await self.session.rollback()
                    logger.error("IntegrityError encountered during bulk insert.")

    def _get_date_range(self):
        # Get current UTC time
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=self.retention_days)

        # Format as ISO 8601 string with 'Z' for UTC
        now_iso_ts = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-3] + "Z"
        past_iso_ts = past.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-3] + "Z"

        # URL encode the timestamps
        return "?StartDate=" + quote(past_iso_ts) + "&EndDate=" + quote(now_iso_ts)