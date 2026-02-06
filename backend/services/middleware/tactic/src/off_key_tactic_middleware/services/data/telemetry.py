"""Use cases for telemetry data queries."""

from datetime import datetime
from typing import Optional, Any

from off_key_core.config.logs import logger

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
        after_timestamp: Optional[datetime],
        paginated: bool,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        records = await self._repository.list_data(
            charger_id=charger_id,
            telemetry_type=telemetry_type,
            limit=limit,
            after_timestamp=after_timestamp,
        )

        logger.info(
            f"Retrieved {len(records)} telemetry records for "
            f"{charger_id}/{telemetry_type}"
        )

        formatted = [
            {
                "timestamp": record.timestamp.isoformat(),
                "value": record.value,
            }
            for record in records
        ]

        if not paginated:
            return formatted

        return {
            "data": formatted,
            "pagination": {
                "limit": limit,
                "has_more": len(formatted) == limit,
                "next_cursor": formatted[-1]["timestamp"] if formatted else None,
            },
        }
