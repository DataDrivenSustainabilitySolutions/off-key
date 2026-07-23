"""Read use cases for persisted static monitoring evidence."""

from ...repositories import MonitoringEvidenceRepository


class MonitoringEvidenceService:
    """Application-level evidence queries for telemetry chart overlays."""

    def __init__(self, repository: MonitoringEvidenceRepository):
        self._repository = repository

    async def list_evidence(
        self,
        *,
        charger_id: str,
        telemetry_type: str | None,
        limit: int,
    ) -> list[dict[str, object]]:
        rows = await self._repository.list_by_charger(
            charger_id=charger_id,
            telemetry_type=telemetry_type,
            limit=limit,
        )
        return [
            {
                "service_id": row.service_id,
                "timestamp": row.timestamp,
                "sequence_number": row.sequence_number,
                "charger_id": row.charger_id,
                "sensor_set": row.sensor_set,
                "p_value": row.p_value,
                "e_value": row.e_value,
                "e_value_is_infinite": row.e_value_is_infinite,
                "log_e_value": row.log_e_value,
                "restarted_martingale": row.restarted_martingale,
                "restarted_martingale_is_infinite": (
                    row.restarted_martingale_is_infinite
                ),
                "log_restarted_martingale": row.log_restarted_martingale,
                "threshold": row.threshold,
                "alarm": row.alarm,
            }
            for row in reversed(rows)
        ]
