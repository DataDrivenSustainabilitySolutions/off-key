"""Use cases for anomaly operations."""

from datetime import datetime

from off_key_core.config.logs import logger
from off_key_core.db.models import Anomaly
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
        telemetry_type: str | None,
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
                "value_type": anomaly.value_type,
                "sensor_set": anomaly.sensor_set,
            }
            for anomaly_id, anomaly in rows
        ]

    async def count_anomalies(self, *, since: datetime | None = None) -> int:
        return await self._repository.count_since(since=since)

    async def create_anomaly(self, *, payload: AnomalyCreateRequest) -> dict[str, str]:
        resolved_value_type = self._resolve_value_type(
            anomaly_type=payload.anomaly_type,
            value_type=payload.value_type,
        )
        anomaly = Anomaly(
            charger_id=payload.charger_id,
            timestamp=payload.timestamp,
            telemetry_type=payload.telemetry_type,
            anomaly_type=payload.anomaly_type,
            anomaly_value=payload.anomaly_value,
            value_type=resolved_value_type,
            sensor_set=self._normalize_sensor_set(payload.sensor_set),
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

    @staticmethod
    def _resolve_value_type(*, anomaly_type: str, value_type: str | None) -> str:
        if value_type is not None:
            return value_type
        if anomaly_type.lower().startswith("ml_tailprob_"):
            return "tail_pvalue"
        if anomaly_type.lower().startswith("ml_conformal_static_"):
            return "conformal_pvalue"
        return "zscore"

    @staticmethod
    def _normalize_sensor_set(sensor_set: list[str] | None) -> list[str] | None:
        if not sensor_set:
            return None

        normalized = []
        seen = set()
        for sensor in sensor_set:
            sensor_name = sensor.strip()
            if sensor_name and sensor_name not in seen:
                normalized.append(sensor_name)
                seen.add(sensor_name)
        return normalized or None

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
