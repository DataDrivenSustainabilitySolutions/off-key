"""Use cases for telemetry data queries."""

from datetime import UTC, datetime, timedelta
from typing import Any

from off_key_core.config.logs import logger

from ...domain import ValidationError
from ...repositories import TelemetryRepository


class TelemetryQueryService:
    """Application-level telemetry query use cases."""

    def __init__(self, repository: TelemetryRepository):
        self._repository = repository

    async def list_types(self, *, charger_id: str, limit: int) -> list[str]:
        types = await self._repository.list_types(charger_id=charger_id, limit=limit)
        logger.info(f"Retrieved {len(types)} telemetry types for charger {charger_id}")
        return types

    async def get_telemetry_data(
        self,
        *,
        charger_id: str,
        telemetry_type: str,
        limit: int,
        after_timestamp: datetime | None,
        after_created: datetime | None,
        after_event_timestamp: datetime | None,
        paginated: bool,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        records = await self._repository.list_data(
            charger_id=charger_id,
            telemetry_type=telemetry_type,
            limit=limit,
            after_timestamp=after_timestamp,
            after_created=after_created,
            after_event_timestamp=after_event_timestamp,
        )

        logger.info(
            f"Retrieved {len(records)} telemetry records for "
            f"{charger_id}/{telemetry_type}"
        )

        formatted = [
            {
                "timestamp": timestamp.isoformat(),
                "value": value,
                "created": (created or timestamp).isoformat(),
            }
            for timestamp, value, created in records
        ]

        if not paginated:
            return formatted

        return {
            "data": formatted,
            "pagination": {
                "limit": limit,
                "has_more": len(formatted) == limit,
                "next_cursor": (
                    {
                        "created": formatted[-1]["created"],
                        "timestamp": formatted[-1]["timestamp"],
                    }
                    if formatted
                    else None
                ),
            },
        }

    async def get_telemetry_range(
        self,
        *,
        charger_id: str,
        telemetry_type: str,
        start: datetime | None,
        end: datetime | None,
        buckets: int,
    ) -> list[dict[str, Any]]:
        """Return a downsampled view of stored history; no start means all of it."""
        end = end or datetime.now(UTC)
        if start is not None and start >= end:
            raise ValidationError("Telemetry range start must precede its end")
        if start is None:
            start = await self._repository.first_timestamp(
                charger_id=charger_id, telemetry_type=telemetry_type
            )
            # A stored series that begins after the requested end has nothing to show.
            if start is None or start > end:
                return []
            if start == end:
                start = end - timedelta(seconds=1)
        records = await self._repository.list_range(
            charger_id=charger_id,
            telemetry_type=telemetry_type,
            start=start,
            end=end,
            buckets=buckets,
        )
        logger.info(
            f"Retrieved {len(records)} range points for {charger_id}/{telemetry_type}"
        )
        return [
            {"timestamp": timestamp.isoformat(), "value": value}
            for timestamp, value in records
        ]
