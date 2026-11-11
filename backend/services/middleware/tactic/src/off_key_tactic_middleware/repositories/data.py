"""SQLAlchemy repositories for TACTIC data-service use cases."""

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Literal

from off_key_core.db.models import (
    Anomaly,
    AnomalyIdentity,
    MemberFavorite,
    MonitoringEvidence,
    Telemetry,
    User,
)
from off_key_core.schemas.alarms import (
    MULTIVARIATE_TELEMETRY_TYPE,
    PROBABILITY_VALUE_TYPES,
    AlarmCursor,
)
from off_key_core.schemas.devices import MeasurementHistory
from off_key_core.schemas.user import normalize_email
from sqlalchemy import (
    ColumnElement,
    Text,
    and_,
    case,
    delete,
    distinct,
    false,
    func,
    not_,
    or_,
    select,
    true,
    tuple_,
)
from sqlalchemy.dialects.postgresql import array, insert
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from .anomaly_filters import AnomalyFilters, ReadingScope

# An anomaly row and its public identity share this natural key.
_ANOMALY_IDENTITY_JOIN = and_(
    Anomaly.charger_id == AnomalyIdentity.charger_id,
    Anomaly.timestamp == AnomalyIdentity.timestamp,
    Anomaly.telemetry_type == AnomalyIdentity.telemetry_type,
    Anomaly.service_id == AnomalyIdentity.service_id,
)


def _has_sensor_set() -> ColumnElement[bool]:
    # Rows written before sensor sets, and manual alarms, store SQL or JSON null.
    return (
        case(
            (
                func.json_typeof(Anomaly.sensor_set) == "array",
                func.json_array_length(Anomaly.sensor_set),
            ),
            else_=0,
        )
        > 0
    )


def _reading_keys():
    """The readings an alarm is about: its sensor set, else its telemetry type."""
    return func.json_array_elements_text(
        case(
            (_has_sensor_set(), Anomaly.sensor_set),
            else_=func.json_build_array(Anomaly.telemetry_type),
        )
    ).table_valued("value")


def _in_scope(scope: ReadingScope) -> ColumnElement[bool]:
    keys = _reading_keys()
    touches = (
        select(true())
        .select_from(keys)
        .where(tuple_(Anomaly.charger_id, keys.c.value).in_(sorted(scope.pairs)))
        .exists()
    )
    if scope.whole_entities:
        touches = or_(
            touches,
            and_(
                Anomaly.telemetry_type == MULTIVARIATE_TELEMETRY_TYPE,
                not_(_has_sensor_set()),
                Anomaly.charger_id.in_(sorted(scope.whole_entities)),
            ),
        )
    # The plain entity test lets the charger_id index narrow the scan first.
    return and_(Anomaly.charger_id.in_(sorted(scope.entities)), touches)


def _matching(filters: AnomalyFilters) -> list[ColumnElement[bool]]:
    conditions = [
        _in_scope(scope)
        for scope in (filters.scope, filters.reading)
        if scope is not None
    ]
    if filters.service_id is not None:
        conditions.append(Anomaly.service_id == filters.service_id)
    if filters.since is not None:
        conditions.append(Anomaly.timestamp >= filters.since)
    if filters.until is not None:
        conditions.append(Anomaly.timestamp < filters.until)
    if filters.max_p_value is not None:
        conditions.append(Anomaly.value_type.in_(PROBABILITY_VALUE_TYPES))
        conditions.append(Anomaly.anomaly_value <= filters.max_p_value)
    return conditions


class TelemetryRepository:
    """Persistence operations for telemetry."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def history(
        self,
        *,
        charger_id: str,
        telemetry_type: str,
        start: datetime,
        end: datetime,
        buckets: int,
        view: Literal["auto", "raw"],
        window_ms: int | None,
    ) -> MeasurementHistory:
        from .telemetry_history import read_history

        return await read_history(
            self._session,
            charger_id=charger_id,
            telemetry_type=telemetry_type,
            start=start,
            end=end,
            buckets=buckets,
            view=view,
            window_ms=window_ms,
        )

    async def list_data(
        self,
        *,
        charger_id: str,
        telemetry_type: str,
        limit: int,
        after_timestamp: datetime | None,
        after_created: datetime | None,
        after_event_timestamp: datetime | None,
    ) -> list[tuple[datetime, float | None, datetime | None]]:
        query = select(Telemetry.timestamp, Telemetry.value, Telemetry.created).where(
            Telemetry.charger_id == charger_id,
            Telemetry.type == telemetry_type,
        )
        if after_timestamp is not None:
            query = query.where(Telemetry.timestamp < after_timestamp)
        if after_created is not None:
            if after_event_timestamp is None:
                raise ValueError(
                    "after_event_timestamp is required when after_created is provided"
                )
            query = query.where(
                or_(
                    Telemetry.created > after_created,
                    and_(
                        Telemetry.created == after_created,
                        Telemetry.timestamp > after_event_timestamp,
                    ),
                )
            ).order_by(Telemetry.created.asc(), Telemetry.timestamp.asc())
        else:
            query = query.order_by(Telemetry.timestamp.desc())

        query = query.limit(limit)
        result = await self._session.execute(query)
        return [
            (timestamp, value, created) for timestamp, value, created in result.all()
        ]

    async def first_timestamp(
        self, *, charger_id: str, telemetry_type: str
    ) -> datetime | None:
        return await self._session.scalar(
            select(func.min(Telemetry.timestamp)).where(
                Telemetry.charger_id == charger_id,
                Telemetry.type == telemetry_type,
                Telemetry.value.is_not(None),
            )
        )

    async def list_range(
        self,
        *,
        charger_id: str,
        telemetry_type: str,
        start: datetime,
        end: datetime,
        buckets: int,
    ) -> list[tuple[datetime, float]]:
        """Return each time bucket's lowest and highest value, in time order.

        Buckets holding one or two rows return them all, so sparse ranges come
        back raw; dense ranges shrink to at most two points per bucket while
        spikes keep their real time and value.
        """
        width = max((end - start) / buckets, timedelta(microseconds=1))
        bucket = func.date_bin(width, Telemetry.timestamp, start)
        ranked = (
            select(
                Telemetry.timestamp,
                Telemetry.value,
                func.row_number()
                .over(
                    partition_by=bucket,
                    order_by=(Telemetry.value.asc(), Telemetry.timestamp.asc()),
                )
                .label("low"),
                func.row_number()
                .over(
                    partition_by=bucket,
                    order_by=(Telemetry.value.desc(), Telemetry.timestamp.asc()),
                )
                .label("high"),
            )
            .where(
                Telemetry.charger_id == charger_id,
                Telemetry.type == telemetry_type,
                Telemetry.value.is_not(None),
                Telemetry.timestamp >= start,
                Telemetry.timestamp <= end,
            )
            .subquery()
        )
        query = (
            select(ranked.c.timestamp, ranked.c.value)
            .where(or_(ranked.c.low == 1, ranked.c.high == 1))
            .order_by(ranked.c.timestamp.asc())
        )
        result = await self._session.execute(query)
        return [(timestamp, value) for timestamp, value in result.all()]


class UserRepository:
    """Persistence operations for users."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_email(self, *, email: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.email == normalize_email(email))
        )
        return result.scalars().first()


class FavoriteRepository:
    """Persistence operations for member favorites."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list(
        self, *, user_id: int, kind: str | None = None
    ) -> list[MemberFavorite]:
        query = select(MemberFavorite).where(MemberFavorite.user_id == user_id)
        if kind is not None:
            query = query.where(MemberFavorite.kind == kind)
        query = query.order_by(
            MemberFavorite.created_at, MemberFavorite.kind, MemberFavorite.item_id
        )
        return list((await self._session.scalars(query)).all())

    async def get(self, *, user_id: int, kind: str, item_id: str):
        return await self._session.get(MemberFavorite, (user_id, kind, item_id))

    async def count(self, *, user_id: int) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(MemberFavorite)
            .where(MemberFavorite.user_id == user_id)
        )
        return count or 0

    async def add(self, *, user_id: int, kind: str, item_id: str) -> None:
        # A concurrent add of the same favorite is not an error.
        await self._session.execute(
            insert(MemberFavorite)
            .values(user_id=user_id, kind=kind, item_id=item_id)
            .on_conflict_do_nothing()
        )

    async def remove(self, *, user_id: int, kind: str, item_id: str) -> None:
        await self._session.execute(
            delete(MemberFavorite).where(
                MemberFavorite.user_id == user_id,
                MemberFavorite.kind == kind,
                MemberFavorite.item_id == item_id,
            )
        )


class AnomalyRepository:
    """Persistence operations for anomalies."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def page(
        self,
        filters: AnomalyFilters,
        *,
        before: AlarmCursor | None,
        limit: int,
    ) -> list[tuple[str, Anomaly]]:
        """Matching alarms, newest first, after a cursor."""
        query = (
            select(AnomalyIdentity.anomaly_id, Anomaly)
            .select_from(Anomaly)
            .join(AnomalyIdentity, _ANOMALY_IDENTITY_JOIN)
            .where(*_matching(filters))
            .order_by(Anomaly.timestamp.desc(), AnomalyIdentity.anomaly_id.desc())
            .limit(limit)
        )
        if before is not None:
            query = query.where(
                tuple_(Anomaly.timestamp, AnomalyIdentity.anomaly_id)
                < tuple_(before.timestamp, before.alarm_id)
            )
        result = await self._session.execute(query)
        return [(anomaly_id, anomaly) for anomaly_id, anomaly in result.all()]

    async def summarize(
        self, filters: AnomalyFilters
    ) -> tuple[int, int, datetime | None]:
        """Count, distinct entities and newest time of every matching alarm."""
        result = await self._session.execute(
            select(
                func.count(),
                func.count(distinct(Anomaly.charger_id)),
                func.max(Anomaly.timestamp),
            )
            .select_from(Anomaly)
            .join(AnomalyIdentity, _ANOMALY_IDENTITY_JOIN)
            .where(*_matching(filters))
        )
        count, entities, latest = result.one()
        return count, entities, latest

    async def reading_counts(
        self, scope: ReadingScope | None
    ) -> list[tuple[str, str, int]]:
        """Alarms per recorded reading in a scope, multivariate rows per sensor."""
        keys = _reading_keys()
        result = await self._session.execute(
            select(Anomaly.charger_id, keys.c.value, func.count())
            .select_from(Anomaly)
            .join(AnomalyIdentity, _ANOMALY_IDENTITY_JOIN)
            .join(keys, true())
            .where(
                keys.c.value != MULTIVARIATE_TELEMETRY_TYPE,
                *_matching(AnomalyFilters(scope=scope)),
            )
            .group_by(Anomaly.charger_id, keys.c.value)
        )
        return [(entity, key, count) for entity, key, count in result.all()]

    async def timeline(
        self, filters: AnomalyFilters, *, limit: int
    ) -> list[tuple[datetime, str, str, str, object]]:
        """Matching alarms oldest first: when, by which monitor, about what."""
        result = await self._session.execute(
            select(
                Anomaly.timestamp,
                Anomaly.service_id,
                Anomaly.charger_id,
                Anomaly.telemetry_type,
                Anomaly.sensor_set,
            )
            .where(*_matching(filters))
            .order_by(Anomaly.timestamp, Anomaly.service_id)
            .limit(limit)
        )
        return [
            (timestamp, monitor, entity, key, sensor_set)
            for timestamp, monitor, entity, key, sensor_set in result.all()
        ]

    async def count_since(self, *, since: datetime | None = None) -> int:
        query = select(func.count()).select_from(Anomaly)
        if since is not None:
            query = query.where(Anomaly.timestamp > since)
        result = await self._session.execute(query)
        return result.scalar_one()

    async def add(self, anomaly: Anomaly) -> str:
        self._session.add(anomaly)
        await self._session.flush()
        identity_result = await self._session.execute(
            select(AnomalyIdentity.anomaly_id).where(
                AnomalyIdentity.charger_id == anomaly.charger_id,
                AnomalyIdentity.timestamp == anomaly.timestamp,
                AnomalyIdentity.telemetry_type == anomaly.telemetry_type,
                AnomalyIdentity.service_id == anomaly.service_id,
            )
        )
        anomaly_id = identity_result.scalar_one_or_none()
        if anomaly_id is not None:
            return str(anomaly_id)

        # Backward-compatible fallback for environments where the
        # anomaly_identity insert trigger has not been installed yet.
        identity = AnomalyIdentity(
            charger_id=anomaly.charger_id,
            timestamp=anomaly.timestamp,
            telemetry_type=anomaly.telemetry_type,
            service_id=anomaly.service_id,
        )
        self._session.add(identity)
        await self._session.flush()
        await self._session.refresh(identity)
        return str(identity.anomaly_id)

    async def get_by_anomaly_id(
        self,
        *,
        anomaly_id: str,
    ) -> tuple[str, Anomaly] | None:
        result = await self._session.execute(
            select(AnomalyIdentity.anomaly_id, Anomaly)
            .join(Anomaly, _ANOMALY_IDENTITY_JOIN)
            .where(AnomalyIdentity.anomaly_id == anomaly_id)
        )
        row = result.first()
        if row is None:
            return None
        return row[0], row[1]

    async def delete(self, anomaly: Anomaly) -> None:
        await self._session.delete(anomaly)


# Recorded keys by entity; None stands for every key of that entity.
EvidenceScope = Mapping[str, frozenset[str] | None]


def _evidence_scope(scope: EvidenceScope) -> ColumnElement[bool]:
    """Evidence of these entities that covers at least one of their keys."""
    clauses = [
        MonitoringEvidence.charger_id == entity
        if keys is None
        else and_(
            MonitoringEvidence.charger_id == entity,
            MonitoringEvidence.sensor_set.op("?|")(array(sorted(keys), type_=Text)),
        )
        for entity, keys in scope.items()
    ]
    return or_(*clauses) if clauses else false()


class MonitoringEvidenceRepository:
    """Read-only persistence operations for static monitoring evidence."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_by_scope(
        self, *, scope: EvidenceScope, limit: int
    ) -> list[MonitoringEvidence]:
        query = (
            select(MonitoringEvidence)
            .where(_evidence_scope(scope))
            .order_by(MonitoringEvidence.timestamp.desc())
            .limit(limit)
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def list_chart(
        self,
        *,
        scope: EvidenceScope,
        after_created: datetime | None,
        after_timestamp: datetime | None,
        after_service_id: str | None,
        after_sequence_number: int | None,
        limit: int,
        service_id: str | None = None,
    ) -> list[
        Row[
            tuple[
                str,
                datetime,
                int,
                str,
                list[str],
                dict[str, str],
                str,
                str | None,
                float | None,
                float | None,
                list[dict[str, object]],
                list[dict[str, object]],
                list[dict[str, object]],
                list[dict[str, object]],
                float,
                bool,
                datetime | None,
            ]
        ]
    ]:
        query = select(
            MonitoringEvidence.service_id,
            MonitoringEvidence.timestamp,
            MonitoringEvidence.sequence_number,
            MonitoringEvidence.charger_id,
            MonitoringEvidence.sensor_set,
            MonitoringEvidence.input_timestamps,
            MonitoringEvidence.strategy,
            MonitoringEvidence.model_type,
            MonitoringEvidence.anomaly_score,
            MonitoringEvidence.restarted_martingale,
            MonitoringEvidence.tracker_results,
            MonitoringEvidence.detector_results,
            MonitoringEvidence.detector_inputs,
            MonitoringEvidence.forecasts,
            MonitoringEvidence.threshold,
            MonitoringEvidence.alarm,
            MonitoringEvidence.created,
        ).where(_evidence_scope(scope))

        if service_id is not None:
            query = query.where(MonitoringEvidence.service_id == service_id)

        if after_created is not None:
            if (
                after_timestamp is None
                or after_service_id is None
                or after_sequence_number is None
            ):
                raise ValueError(
                    "after_timestamp, after_service_id and after_sequence_number "
                    "are required when after_created is provided"
                )
            query = query.where(
                or_(
                    MonitoringEvidence.created > after_created,
                    and_(
                        MonitoringEvidence.created == after_created,
                        MonitoringEvidence.timestamp == after_timestamp,
                        MonitoringEvidence.service_id > after_service_id,
                    ),
                    and_(
                        MonitoringEvidence.created == after_created,
                        MonitoringEvidence.timestamp == after_timestamp,
                        MonitoringEvidence.service_id == after_service_id,
                        MonitoringEvidence.sequence_number > after_sequence_number,
                    ),
                    and_(
                        MonitoringEvidence.created == after_created,
                        MonitoringEvidence.timestamp > after_timestamp,
                    ),
                )
            ).order_by(
                MonitoringEvidence.created.asc(),
                MonitoringEvidence.timestamp.asc(),
                MonitoringEvidence.service_id.asc(),
                MonitoringEvidence.sequence_number.asc(),
            )
        else:
            query = query.order_by(
                MonitoringEvidence.created.desc(),
                MonitoringEvidence.timestamp.desc(),
                MonitoringEvidence.service_id.desc(),
                MonitoringEvidence.sequence_number.desc(),
            )

        result = await self._session.execute(query.limit(limit))
        rows = list(result.all())
        return rows if after_created is not None else list(reversed(rows))
