"""Use cases for alarms, by catalogue device and reading."""

from datetime import datetime

from aberration_core.config.logs import logger
from aberration_core.db.models import Anomaly
from aberration_core.schemas.alarms import (
    MULTIVARIATE_TELEMETRY_TYPE,
    Alarm,
    AlarmCreate,
    AlarmCursor,
    AlarmPage,
    AlarmQuery,
    AlarmSummary,
    resolve_alarm_value_type,
)
from aberration_core.schemas.system import SystemSnapshot
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain import (
    ConflictError,
    InfrastructureError,
    NotFoundError,
    ValidationError,
)
from ...repositories import AnomalyRepository
from ...repositories.anomaly_filters import AnomalyFilters, ReadingScope
from .alarm_catalogue import AlarmCatalogue


class AlarmService:
    """Application-level alarm use cases."""

    def __init__(self, session: AsyncSession, repository: AnomalyRepository):
        self._session = session
        self._repository = repository

    async def list_alarms(
        self,
        catalogue: SystemSnapshot,
        *,
        device_id: str | None,
        stream_ids: list[str] | None,
        service_id: str | None,
        limit: int,
    ) -> list[Alarm]:
        """Newest alarms of a device, of readings, or of every reading."""
        if device_id is not None and stream_ids:
            raise ValidationError("Name either a device or readings")
        names = AlarmCatalogue(catalogue)
        scope = (
            names.device_scope(device_id)
            if device_id is not None
            else names.scope(stream_ids)[0]
            if stream_ids
            else None
        )
        if scope is not None and not scope.pairs:
            return []
        rows = await self._repository.page(
            AnomalyFilters(scope=scope, service_id=service_id), before=None, limit=limit
        )
        logger.debug(
            "event=tactic.alarms_read device_id=%s readings=%s count=%s",
            device_id,
            len(stream_ids or []),
            len(rows),
        )
        return [names.alarm(alarm_id, row) for alarm_id, row in rows]

    async def query(self, query: AlarmQuery, catalogue: SystemSnapshot) -> AlarmPage:
        """One page of alarms for catalogue readings, with catalogue names."""
        names = AlarmCatalogue(catalogue)
        scope, unknown = (
            (None, []) if query.reading_ids is None else names.scope(query.reading_ids)
        )
        narrowing = None
        if query.reading_id is not None:
            narrowing = names.narrowing(query.reading_id)
            if not narrowing.pairs:
                unknown = sorted({*unknown, query.reading_id})
        if scope is not None and not scope.pairs:
            return AlarmPage(
                items=[],
                next=None,
                summary=AlarmSummary(count=0, devices=0, latest=None),
                readings=[],
                unknown_reading_ids=unknown,
            )
        filters = self._filters(query, scope, narrowing)
        rows = await self._repository.page(
            filters, before=query.before, limit=query.limit + 1
        )
        count, entities, latest = await self._repository.summarize(filters)
        counted = (
            names.reading_count(entity, key, total)
            for entity, key, total in await self._repository.reading_counts(scope)
        )
        readings = sorted(
            (item for item in counted if item is not None),
            key=lambda item: (item.device_label or "", item.label, item.reading_id),
        )
        last = rows[query.limit - 1] if len(rows) > query.limit else None
        return AlarmPage(
            items=[names.alarm(alarm_id, row) for alarm_id, row in rows[: query.limit]],
            next=None
            if last is None
            else AlarmCursor(timestamp=last[1].timestamp, alarm_id=str(last[0])),
            summary=AlarmSummary(count=count, devices=entities, latest=latest),
            readings=readings,
            unknown_reading_ids=unknown,
        )

    @staticmethod
    def _filters(
        query: AlarmQuery, scope: ReadingScope | None, narrowing: ReadingScope | None
    ) -> AnomalyFilters:
        return AnomalyFilters(
            scope=scope,
            reading=narrowing,
            service_id=query.monitor_id,
            since=query.since,
            until=query.until,
            max_p_value=query.max_p_value,
        )

    async def count_alarms(self, *, since: datetime | None = None) -> int:
        return await self._repository.count_since(since=since)

    async def create_alarm(
        self, payload: AlarmCreate, catalogue: SystemSnapshot
    ) -> Alarm:
        names = AlarmCatalogue(catalogue)
        entity, keys = names.recorded(payload.reading_ids)
        anomaly = Anomaly(
            charger_id=entity,
            timestamp=payload.timestamp,
            telemetry_type=keys[0] if len(keys) == 1 else MULTIVARIATE_TELEMETRY_TYPE,
            service_id="",
            anomaly_type=payload.alarm_type,
            anomaly_value=payload.value,
            value_type=resolve_alarm_value_type(
                alarm_type=payload.alarm_type, value_type=payload.value_type
            ),
            sensor_set=keys if len(keys) > 1 else None,
        )

        try:
            # Named before the commit expires the row's attributes.
            alarm = names.alarm(await self._repository.add(anomaly), anomaly)
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ConflictError("Alarm already exists") from exc
        except Exception as exc:
            await self._session.rollback()
            raise InfrastructureError(f"Failed to create alarm: {exc}") from exc

        logger.warning(
            "event=tactic.alarm_created alarm_id=%s device_id=%s alarm_type=%s",
            alarm.alarm_id,
            alarm.device_id,
            alarm.alarm_type,
        )
        return alarm

    async def delete_alarm(self, *, alarm_id: str) -> None:
        row = await self._repository.get_by_anomaly_id(anomaly_id=alarm_id)
        if row is None:
            raise NotFoundError("Alarm not found")
        resolved_alarm_id, anomaly = row

        try:
            await self._repository.delete(anomaly)
            await self._session.commit()
        except Exception as exc:
            await self._session.rollback()
            raise InfrastructureError(f"Failed to delete alarm: {exc}") from exc

        logger.info(
            "event=tactic.alarm_deleted alarm_id=%s timestamp=%s",
            resolved_alarm_id,
            anomaly.timestamp,
        )
