"""Use cases for anomaly operations."""

from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from off_key_core.config.logs import logger
from off_key_core.db.models import Anomaly

from ...domain import InfrastructureError, NotFoundError
from ...repositories import AnomalyRepository
from ...schemas import AnomalyCreateRequest


class AnomalyService:
    """Application-level anomaly use cases."""

    def __init__(self, session: AsyncSession, repository: AnomalyRepository):
        self._session = session
        self._repository = repository

    async def list_anomalies(
        self,
        *,
        charger_id: str,
        telemetry_type: Optional[str],
        limit: int,
    ) -> list[dict[str, object]]:
        anomalies = await self._repository.list_by_charger(
            charger_id=charger_id,
            telemetry_type=telemetry_type,
            limit=limit,
        )
        logger.info(
            f"Retrieved {len(anomalies)} anomalies for charger {charger_id} "
            f"(telemetry_type={telemetry_type})"
        )
        return [
            {
                "charger_id": anomaly.charger_id,
                "timestamp": anomaly.timestamp,
                "telemetry_type": anomaly.telemetry_type,
                "anomaly_type": anomaly.anomaly_type,
                "anomaly_value": anomaly.anomaly_value,
            }
            for anomaly in anomalies
        ]

    async def create_anomaly(self, *, payload: AnomalyCreateRequest) -> dict[str, str]:
        anomaly = Anomaly(
            charger_id=payload.charger_id,
            timestamp=payload.timestamp,
            telemetry_type=payload.telemetry_type,
            anomaly_type=payload.anomaly_type,
            anomaly_value=payload.anomaly_value,
        )

        try:
            created = await self._repository.add(anomaly)
            await self._session.commit()
        except Exception as exc:
            await self._session.rollback()
            raise InfrastructureError(f"Failed to create anomaly: {exc}") from exc

        logger.warning(
            f"Anomaly created | Charger: {payload.charger_id} | "
            f"Type: {payload.anomaly_type} | Value: {payload.anomaly_value}"
        )
        return {"message": "Anomaly created", "anomaly_id": created.charger_id}

    async def delete_anomaly(
        self,
        *,
        charger_id: str,
        timestamp: datetime,
        telemetry_type: str,
    ) -> dict[str, str]:
        anomaly = await self._repository.get(
            charger_id=charger_id,
            timestamp=timestamp,
            telemetry_type=telemetry_type,
        )
        if anomaly is None:
            raise NotFoundError("Anomaly not found")

        try:
            await self._repository.delete(anomaly)
            await self._session.commit()
        except Exception as exc:
            await self._session.rollback()
            raise InfrastructureError(f"Failed to delete anomaly: {exc}") from exc

        logger.info(f"Deleted anomaly for charger {charger_id} at {timestamp}")
        return {"message": "Anomaly deleted"}
