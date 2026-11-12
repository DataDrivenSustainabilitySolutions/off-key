"""An event's evidence and transactional deletion of reviewed event selections."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from off_key_core.config.logs import logger
from off_key_core.db.models import (
    AlarmDeletion,
    Anomaly,
    AnomalyIdentity,
    MonitoringEvidence,
)
from off_key_core.schemas.alarms import (
    AlarmDeletionPreview,
    AlarmDetail,
    AlarmSelection,
)
from off_key_core.schemas.devices import ChartEvidence
from off_key_core.schemas.system import SystemSnapshot
from sqlalchemy import Text, cast, delete, func, insert, literal, select, update
from sqlalchemy.dialects.postgresql import ARRAY, array
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain import NotFoundError, ValidationError
from ...repositories.data import ANOMALY_IDENTITY_JOIN, matching_anomalies
from .alarm_catalogue import AlarmCatalogue
from .catalogue_data import CatalogueDataService


class AlarmActions:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def detail(self, alarm_id: str, catalogue: SystemSnapshot) -> AlarmDetail:
        row = (
            await self.session.execute(
                select(Anomaly)
                .join(AnomalyIdentity, ANOMALY_IDENTITY_JOIN)
                .where(AnomalyIdentity.anomaly_id == alarm_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("This anomaly was deleted or is no longer retained")
        evidence = None
        if row.service_id:
            # Never attach a nearby observation or another monitor's result.
            evidence = (
                await self.session.execute(
                    select(MonitoringEvidence)
                    .where(
                        MonitoringEvidence.service_id == row.service_id,
                        MonitoringEvidence.charger_id == row.charger_id,
                        MonitoringEvidence.timestamp == row.timestamp,
                        MonitoringEvidence.alarm.is_(True),
                    )
                    .order_by(MonitoringEvidence.sequence_number.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        return AlarmDetail(
            alarm=AlarmCatalogue(catalogue).alarm(alarm_id, row),
            evidence=ChartEvidence.model_validate(
                CatalogueDataService(self.session, catalogue).chart_row(evidence)
            )
            if evidence is not None
            else None,
        )

    async def preview(
        self, selection: AlarmSelection, catalogue: SystemSnapshot
    ) -> AlarmDeletionPreview:
        conditions = []
        if selection.query is not None:
            filters, unknown = AlarmCatalogue(catalogue).filters(selection.query)
            if unknown:
                raise ValidationError(
                    "Some selected readings no longer exist. "
                    "Refresh Reporting before deleting."
                )
            conditions = matching_anomalies(filters)
            if selection.exclude_ids:
                conditions.append(
                    AnomalyIdentity.anomaly_id.not_in(selection.exclude_ids)
                )
        else:
            conditions = [AnomalyIdentity.anomaly_id.in_(selection.alarm_ids or [])]
        now = datetime.now(UTC)
        token, expires = str(uuid4()), now + timedelta(minutes=10)
        # Aggregate inside PostgreSQL: an all-matching preview has a small wire
        # response regardless of count. The snapshot contains exact identities,
        # so late arrivals and later catalogue changes cannot widen deletion.
        snapshot = (
            select(
                literal(token),
                func.coalesce(
                    func.array_agg(AnomalyIdentity.anomaly_id),
                    cast(array([], type_=Text), ARRAY(Text)),
                ),
                func.count(),
                literal(expires),
            )
            .select_from(Anomaly)
            .join(AnomalyIdentity, ANOMALY_IDENTITY_JOIN)
            .where(*conditions)
        )
        try:
            await self.session.execute(
                delete(AlarmDeletion).where(AlarmDeletion.expires_at <= now)
            )
            count = (
                await self.session.execute(
                    insert(AlarmDeletion)
                    .from_select(["id", "alarm_ids", "count", "expires_at"], snapshot)
                    .returning(AlarmDeletion.count)
                )
            ).scalar_one()
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return AlarmDeletionPreview(token=token, count=count, expires_at=expires)

    async def delete(self, token: str) -> int:
        try:
            preview = (
                await self.session.execute(
                    select(AlarmDeletion.expires_at, AlarmDeletion.deleted_count)
                    .where(AlarmDeletion.id == token)
                    .with_for_update()
                )
            ).first()
            if preview is None or preview.expires_at <= datetime.now(UTC):
                raise NotFoundError(
                    "This deletion preview expired. Review the selection again."
                )
            if preview.deleted_count is not None:
                await self.session.commit()
                return preview.deleted_count
            ids = select(func.unnest(AlarmDeletion.alarm_ids)).where(
                AlarmDeletion.id == token
            )
            matches = (
                select(1)
                .select_from(AnomalyIdentity)
                .where(ANOMALY_IDENTITY_JOIN, AnomalyIdentity.anomaly_id.in_(ids))
                .exists()
            )
            removed = (
                delete(Anomaly)
                .where(matches)
                .returning(Anomaly.timestamp)
                .cte("removed")
            )
            count = (
                await self.session.execute(select(func.count()).select_from(removed))
            ).scalar_one()
            await self.session.execute(
                update(AlarmDeletion)
                .where(AlarmDeletion.id == token)
                .values(deleted_count=count, alarm_ids=[])
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        logger.info(
            "event=tactic.alarms_deleted selection_id=%s count=%s", token, count
        )
        return count
