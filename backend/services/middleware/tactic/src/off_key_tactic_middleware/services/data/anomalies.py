"""Use cases for anomaly operations."""

from datetime import datetime
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from off_key_core.config.logs import logger
from off_key_core.db.models import Anomaly

from ...domain import ConflictError, InfrastructureError, NotFoundError
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
        rows = await self._repository.list_by_charger(
            charger_id=charger_id,
            telemetry_type=telemetry_type,
            limit=limit,
        )
        logger.info(
            f"Retrieved {len(rows)} anomalies for charger {charger_id} "
            f"(telemetry_type={telemetry_type})"
        )
        return [
            {
                "anomaly_id": str(anomaly_id),
                "charger_id": anomaly.charger_id,
                "timestamp": anomaly.timestamp,
                "telemetry_type": anomaly.telemetry_type,
                "anomaly_type": anomaly.anomaly_type,
                "anomaly_value": anomaly.anomaly_value,
            }
            for anomaly_id, anomaly in rows
        ]

    async def count_anomalies(self, *, since: Optional[datetime] = None) -> int:
        return await self._repository.count_since(since=since)

    async def create_anomaly(self, *, payload: AnomalyCreateRequest) -> dict[str, str]:
        anomaly = Anomaly(
            charger_id=payload.charger_id,
            timestamp=payload.timestamp,
            telemetry_type=payload.telemetry_type,
            anomaly_type=payload.anomaly_type,
            anomaly_value=payload.anomaly_value,
        )

        try:
            created_anomaly_id = await self._repository.add(anomaly)
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ConflictError("Anomaly already exists") from exc
        except Exception as exc:
            await self._session.rollback()
            raise InfrastructureError(f"Failed to create anomaly: {exc}") from exc

        logger.warning(
            f"Anomaly created | Charger: {payload.charger_id} | "
            f"Type: {payload.anomaly_type} | Value: {payload.anomaly_value}"
        )
        return {"message": "Anomaly created", "anomaly_id": str(created_anomaly_id)}

    async def delete_anomaly(
        self,
        *,
        anomaly_id: str,
    ) -> dict[str, str]:
        row = await self._repository.get_by_anomaly_id(anomaly_id=anomaly_id)

        if row is None:
            raise NotFoundError("Anomaly not found")
        resolved_anomaly_id, anomaly = row

        try:
            await self._repository.delete(anomaly)
            await self._session.commit()
        except Exception as exc:
            await self._session.rollback()
            raise InfrastructureError(f"Failed to delete anomaly: {exc}") from exc

        logger.info(
            "Deleted anomaly | Anomaly ID: %s | Charger: %s | Timestamp: %s",
            resolved_anomaly_id,
            anomaly.charger_id,
            anomaly.timestamp,
        )
        return {"message": "Anomaly deleted"}
