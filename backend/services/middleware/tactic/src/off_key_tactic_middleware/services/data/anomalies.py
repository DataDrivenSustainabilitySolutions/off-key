"""Use cases for anomaly operations."""

from datetime import datetime

from off_key_core.config.logs import logger
from off_key_core.db.models import Anomaly
from off_key_core.schemas.reporting import (
    MULTIVARIATE_TELEMETRY_TYPE,
    AnomalyCursor,
    AnomalyPage,
    AnomalyQuery,
    AnomalySummary,
    ReadingCount,
    ReadingLabel,
    ReportedAnomaly,
)
from off_key_core.schemas.system import SystemSnapshot
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain import ConflictError, InfrastructureError, NotFoundError
from ...repositories import AnomalyRepository
from ...repositories.anomaly_filters import AnomalyFilters, ReadingScope
from ...schemas import AnomalyCreateRequest
from .reporting_scope import CatalogueLabels, reading_scope


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
        logger.debug(
            "event=tactic.anomalies_read charger_id=%s telemetry_type=%s count=%s",
            charger_id,
            telemetry_type,
            len(rows),
        )
        return self._responses(rows)

    async def query(
        self, query: AnomalyQuery, catalogue: SystemSnapshot
    ) -> AnomalyPage:
        """One page of alarms for catalogue readings, labelled from the catalogue."""
        bindings = catalogue.runtime.bindings
        labels = CatalogueLabels(catalogue.document, bindings)
        scope, unknown = (
            (None, [])
            if query.stream_ids is None
            else reading_scope(bindings, query.stream_ids)
        )
        if scope is not None and not scope.pairs:
            return AnomalyPage(
                items=[],
                next=None,
                summary=AnomalySummary(count=0, entities=0, latest=None),
                readings=[],
                unknown_stream_ids=unknown,
            )
        filters = self._filters(query, scope)
        rows = await self._repository.page(
            filters, before=query.before, limit=query.limit + 1
        )
        count, entities, latest = await self._repository.summarize(filters)
        readings = [
            ReadingCount(
                charger_id=entity,
                telemetry_key=key,
                entity_label=labels.entity(entity),
                label=labels.reading(entity, key),
                count=total,
            )
            for entity, key, total in await self._repository.reading_counts(scope)
        ]
        readings.sort(key=lambda item: (item.entity_label, item.label, item.charger_id))
        last = rows[query.limit - 1] if len(rows) > query.limit else None
        return AnomalyPage(
            items=[self._reported(row, labels) for row in rows[: query.limit]],
            next=None
            if last is None
            else AnomalyCursor(timestamp=last[1].timestamp, anomaly_id=str(last[0])),
            summary=AnomalySummary(count=count, entities=entities, latest=latest),
            readings=readings,
            unknown_stream_ids=unknown,
        )

    @staticmethod
    def _filters(query: AnomalyQuery, scope: ReadingScope | None) -> AnomalyFilters:
        reading = query.reading
        return AnomalyFilters(
            scope=scope,
            reading=None
            if reading is None
            else ReadingScope(frozenset({(reading.charger_id, reading.telemetry_key)})),
            service_id=query.service_id,
            since=query.since,
            until=query.until,
            max_p_value=query.max_p_value,
        )

    @staticmethod
    def _reported(row: tuple[str, Anomaly], labels: CatalogueLabels) -> ReportedAnomaly:
        anomaly_id, anomaly = row
        entity = anomaly.charger_id
        multivariate = anomaly.telemetry_type == MULTIVARIATE_TELEMETRY_TYPE
        keys = anomaly.sensor_set or ([] if multivariate else [anomaly.telemetry_type])
        return ReportedAnomaly(
            anomaly_id=str(anomaly_id),
            charger_id=entity,
            timestamp=anomaly.timestamp,
            telemetry_type=anomaly.telemetry_type,
            anomaly_type=anomaly.anomaly_type,
            anomaly_value=anomaly.anomaly_value,
            value_type=anomaly.value_type,
            sensor_set=anomaly.sensor_set,
            service_id=anomaly.service_id or None,
            entity_label=labels.entity(entity),
            telemetry_label=None
            if multivariate
            else labels.reading(entity, anomaly.telemetry_type),
            readings=[
                ReadingLabel(key=key, label=labels.reading(entity, key)) for key in keys
            ],
        )

    @staticmethod
    def _responses(rows: list[tuple[str, Anomaly]]) -> list[dict[str, object]]:
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
                "service_id": anomaly.service_id or None,
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
            service_id="",
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
