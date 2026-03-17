"""SQLAlchemy repositories for TACTIC data-service use cases."""

from datetime import datetime
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from off_key_core.db.models import (
    Anomaly,
    AnomalyIdentity,
    Charger,
    Favorite,
    Telemetry,
    User,
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
        query = select(Charger)
        if active_only:
            query = query.where(Charger.online.is_(True))
        query = query.offset(skip).limit(limit)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def list_active_charger_ids(self, *, skip: int, limit: int) -> list[str]:
        query = (
            select(Charger.charger_id)
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
        query = (
            select(Telemetry.type)
            .where(Telemetry.charger_id == charger_id)
            .distinct()
            .order_by(Telemetry.type.asc())
            .limit(limit)
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def list_data(
        self,
        *,
        charger_id: str,
        telemetry_type: str,
        limit: int,
        after_timestamp: Optional[datetime],
    ) -> list[Telemetry]:
        query = select(Telemetry).where(
            Telemetry.charger_id == charger_id,
            Telemetry.type == telemetry_type,
        )
        if after_timestamp is not None:
            query = query.where(Telemetry.timestamp < after_timestamp)

        query = query.order_by(Telemetry.timestamp.desc()).limit(limit)
        result = await self._session.execute(query)
        return list(result.scalars().all())


class UserRepository:
    """Persistence operations for users."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_email(self, *, email: str) -> Optional[User]:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalars().first()

    async def add(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        await self._session.refresh(user)
        return user


class FavoriteRepository:
    """Persistence operations for favorites."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_by_user_id(self, *, user_id: int) -> list[Favorite]:
        result = await self._session.execute(
            select(Favorite).where(Favorite.user_id == user_id)
        )
        return list(result.scalars().all())

    async def get(self, *, user_id: int, charger_id: str) -> Optional[Favorite]:
        result = await self._session.execute(
            select(Favorite).where(
                Favorite.user_id == user_id,
                Favorite.charger_id == charger_id,
            )
        )
        return result.scalars().first()

    async def add(self, favorite: Favorite) -> None:
        self._session.add(favorite)

    async def delete(self, favorite: Favorite) -> None:
        await self._session.delete(favorite)


class AnomalyRepository:
    """Persistence operations for anomalies."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_by_charger(
        self,
        *,
        charger_id: str,
        telemetry_type: Optional[str],
        limit: int,
    ) -> list[tuple[str, Anomaly]]:
        query = (
            select(AnomalyIdentity.anomaly_id, Anomaly)
            .join(
                Anomaly,
                and_(
                    Anomaly.charger_id == AnomalyIdentity.charger_id,
                    Anomaly.timestamp == AnomalyIdentity.timestamp,
                    Anomaly.telemetry_type == AnomalyIdentity.telemetry_type,
                ),
            )
            .where(Anomaly.charger_id == charger_id)
        )
        if telemetry_type:
            query = query.where(Anomaly.telemetry_type == telemetry_type)
        query = query.order_by(Anomaly.timestamp.desc()).limit(limit)
        result = await self._session.execute(query)
        return [(anomaly_id, anomaly) for anomaly_id, anomaly in result.all()]

    async def count_since(self, *, since: Optional[datetime] = None) -> int:
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
        )
        self._session.add(identity)
        await self._session.flush()
        await self._session.refresh(identity)
        return str(identity.anomaly_id)

    async def get_by_anomaly_id(
        self,
        *,
        anomaly_id: str,
    ) -> Optional[tuple[str, Anomaly]]:
        result = await self._session.execute(
            select(AnomalyIdentity.anomaly_id, Anomaly)
            .join(
                Anomaly,
                and_(
                    Anomaly.charger_id == AnomalyIdentity.charger_id,
                    Anomaly.timestamp == AnomalyIdentity.timestamp,
                    Anomaly.telemetry_type == AnomalyIdentity.telemetry_type,
                ),
            )
            .where(AnomalyIdentity.anomaly_id == anomaly_id)
        )
        row = result.first()
        if row is None:
            return None
        return row[0], row[1]

    async def delete(self, anomaly: Anomaly) -> None:
        await self._session.delete(anomaly)
