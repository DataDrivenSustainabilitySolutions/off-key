"""SQLAlchemy repositories for TACTIC data-service use cases."""

from datetime import datetime, timedelta

from off_key_core.db.collection_runtime import read_collection_runtime
from off_key_core.db.models import (
    Anomaly,
    AnomalyIdentity,
    Charger,
    CollectionBinding,
    MemberFavorite,
    MonitoringEvidence,
    Telemetry,
    User,
)
from off_key_core.schemas.user import normalize_email
from sqlalchemy import and_, delete, func, or_, select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

# An anomaly row and its public identity share this natural key.
_ANOMALY_IDENTITY_JOIN = and_(
    Anomaly.charger_id == AnomalyIdentity.charger_id,
    Anomaly.timestamp == AnomalyIdentity.timestamp,
    Anomaly.telemetry_type == AnomalyIdentity.telemetry_type,
    Anomaly.service_id == AnomalyIdentity.service_id,
)


def _anomaly_listing():
    return (
        select(AnomalyIdentity.anomaly_id, Anomaly)
        .select_from(Anomaly)
        .join(AnomalyIdentity, _ANOMALY_IDENTITY_JOIN)
        .order_by(Anomaly.timestamp.desc())
    )


class ChargerRepository:
    """Persistence operations for chargers."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_chargers(
        self,
        *,
        skip: int,
        limit: int,
        active_only: bool,
    ) -> list[Charger]:
        query = select(Charger).join(CollectionBinding)
        if active_only:
            query = query.where(Charger.online.is_(True))
        query = query.offset(skip).limit(limit)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def list_active_charger_ids(self, *, skip: int, limit: int) -> list[str]:
        query = (
            select(Charger.charger_id)
            .join(CollectionBinding)
            .where(Charger.online.is_(True))
            .offset(skip)
            .limit(limit)
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())


class TelemetryRepository:
    """Persistence operations for telemetry."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_types(self, *, charger_id: str, limit: int) -> list[str]:
        snapshot = await read_collection_runtime(self._session)
        return sorted(
            stream.key
            for stream in snapshot.catalog.streams(selected_only=True)
            if stream.charger_id == charger_id and stream.value_type == "number"
        )[:limit]

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

    async def list_by_charger(
        self,
        *,
        charger_id: str,
        telemetry_type: str | None,
        limit: int,
    ) -> list[tuple[str, Anomaly]]:
        query = _anomaly_listing().where(Anomaly.charger_id == charger_id)
        if telemetry_type:
            query = query.where(Anomaly.telemetry_type == telemetry_type)
        result = await self._session.execute(query.limit(limit))
        return [(anomaly_id, anomaly) for anomaly_id, anomaly in result.all()]

    async def list_report(
        self, *, entity_limit: int, per_entity_limit: int
    ) -> list[tuple[str, Anomaly]]:
        """Read each catalogue entity's bounded history in one statement."""
        entities = (
            select(CollectionBinding.charger_id)
            .order_by(CollectionBinding.charger_id)
            .limit(entity_limit)
            .subquery()
        )
        latest = (
            _anomaly_listing()
            .where(Anomaly.charger_id == entities.c.charger_id)
            .correlate(entities)
            .limit(per_entity_limit)
            .lateral()
        )
        result = await self._session.execute(
            select(latest.c.anomaly_id, aliased(Anomaly, latest))
            .select_from(entities)
            .join(latest, true())
        )
        return [(anomaly_id, anomaly) for anomaly_id, anomaly in result.all()]

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


class MonitoringEvidenceRepository:
    """Read-only persistence operations for static monitoring evidence."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_by_charger(
        self,
        *,
        charger_id: str,
        telemetry_type: str | None,
        limit: int,
    ) -> list[MonitoringEvidence]:
        query = select(MonitoringEvidence).where(
            MonitoringEvidence.charger_id == charger_id
        )
        if telemetry_type:
            query = query.where(MonitoringEvidence.sensor_set.op("?")(telemetry_type))
        query = query.order_by(MonitoringEvidence.timestamp.desc()).limit(limit)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def list_chart_by_charger(
        self,
        *,
        charger_id: str,
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
                list[str],
                dict[str, str],
                str,
                str | None,
                float | None,
                float | None,
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
            MonitoringEvidence.sensor_set,
            MonitoringEvidence.input_timestamps,
            MonitoringEvidence.strategy,
            MonitoringEvidence.model_type,
            MonitoringEvidence.anomaly_score,
            MonitoringEvidence.restarted_martingale,
            MonitoringEvidence.tracker_results,
            MonitoringEvidence.detector_results,
            MonitoringEvidence.detector_inputs,
            MonitoringEvidence.threshold,
            MonitoringEvidence.alarm,
            MonitoringEvidence.created,
        ).where(MonitoringEvidence.charger_id == charger_id)

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
