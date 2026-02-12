"""SQLAlchemy repositories for TACTIC data-service use cases."""

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from off_key_core.db.models import Charger, Telemetry, User, Favorite, Anomaly


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
    ) -> list[Anomaly]:
        query = select(Anomaly).where(Anomaly.charger_id == charger_id)
        if telemetry_type:
            query = query.where(Anomaly.telemetry_type == telemetry_type)
        query = query.order_by(Anomaly.timestamp.desc()).limit(limit)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def add(self, anomaly: Anomaly) -> Anomaly:
        self._session.add(anomaly)
        await self._session.flush()
        await self._session.refresh(anomaly)
        return anomaly

    async def get(
        self,
        *,
        charger_id: str,
        timestamp: datetime,
        telemetry_type: str,
    ) -> Optional[Anomaly]:
        result = await self._session.execute(
            select(Anomaly).where(
                Anomaly.charger_id == charger_id,
                Anomaly.timestamp == timestamp,
                Anomaly.telemetry_type == telemetry_type,
            )
        )
        return result.scalars().first()

    async def delete(self, anomaly: Anomaly) -> None:
        await self._session.delete(anomaly)
