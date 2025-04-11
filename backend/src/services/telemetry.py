import logging

from datetime import datetime, timezone, timedelta
from urllib.parse import unquote
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, cast, DateTime
from sqlalchemy.dialects.postgresql import insert

from ..core.client.pionix import PionixClient
from ..core.config import settings
from ..core.logs import logger
from ..db.models import Charger, Telemetry
from ..utils.date import get_date_range
from ..utils.string import clean_string, string_to_float

logging.getLogger("sqlalchemy.engine").setLevel(logging.CRITICAL)


class TelemetrySyncService:
    def __init__(self, session: AsyncSession, retention_days: int = 14):
        self.session: AsyncSession = session
        self.client = PionixClient(settings.PIONIX_KEY, settings.PIONIX_USER_AGENT)
        self.retention_days = retention_days

    async def sync_telemetry(self):
        # Strip timezone from the datetime
        two_weeks_ago = (datetime.now(timezone.utc) - timedelta(weeks=2)).replace(
            tzinfo=None
        )

        # Query all charger_id where online is True
        stmt = select(Charger.charger_id).where(
            Charger.online, cast(Charger.last_seen, DateTime) >= two_weeks_ago
        )
        result = await self.session.execute(stmt)
        online_charger_ids = result.scalars().all()

        logger.info(f"Synchronization Charger IDs: {online_charger_ids}")

        dr = get_date_range(retention_days=self.retention_days)
        for charger_id in online_charger_ids:

            dm_url = f"chargers/{charger_id}/deviceModel"
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

            # Write values for each hierarchy in database
            for hierarchy in telemetry_hierarchies:
                logger.info(f"Telemetries: {hierarchy} (for {charger_id}).")

                hierarchy = hierarchy.replace("/", "%2F")
                get_url = (
                    f"chargers/{charger_id}/telemetry/{hierarchy}{dr}&Limit=10000"
                )

                logger.info(f"Request URL: {get_url}")

                telemetry = await self.client.get(get_url)
                items = telemetry.get("items", [])

                logger.info(f"Extracted items: {items[0:3]} (first three elements)")

                if not telemetry.get("items"):
                    logger.warning(f"No data retrieved from {get_url}")
                    continue  # No data to insert

                try:
                    telemetry_records = [
                        {
                            "charger_id": charger_id,
                            "timestamp": datetime.fromisoformat(
                                unquote(item["timestamp"]).replace("Z", "+00:00")
                            ).replace(
                                tzinfo=None
                            ),  # Strip timezone for consistency
                            "value": (string_to_float(item["value"])),
                            "type": clean_string(hierarchy),
                            "created": datetime.now(timezone.utc).replace(
                                tzinfo=None
                            ),  # Strip timezone
                        }
                        for item in items
                    ]
                except (KeyError, ValueError, TypeError) as e:
                    # logger.error(f"Error processing telemetry records: {e}")
                    logger.error(f"Error processing telemetry records: {e}")
                    continue

                logger.info("Bulk Insertion: Telemetry")

                # Split telemetry_records into chunks of 2000
                batch_size = 5_000  # Accounts for binding limits
                for i in range(0, len(telemetry_records), batch_size):
                    batch = telemetry_records[i : i + batch_size]
                    try:
                        stmt = insert(Telemetry).values(batch)
                        stmt = (
                            stmt.on_conflict_do_nothing()
                        )  # Skip rows that violate unique constraints
                        await self.session.execute(stmt)
                        await self.session.commit()
                    except IntegrityError:
                        await self.session.rollback()
                        logger.error("IntegrityError encountered during bulk insert.")
                    except Exception as e:
                        await self.session.rollback()
                        logger.error(f"Error during bulk insert: {e}")
