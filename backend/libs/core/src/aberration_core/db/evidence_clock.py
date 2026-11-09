"""A durable commit-order watermark shared by evidence insert transactions."""

from datetime import datetime
from importlib.resources import files

from sqlalchemy import CheckConstraint, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class MonitoringEvidenceClock(Base):
    __tablename__ = "monitoring_evidence_clock"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_created: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    __table_args__ = (CheckConstraint("id = 1", name="ck_evidence_clock_singleton"),)


def install_evidence_clock(connection) -> None:
    # Bootstrap and upgrades install exactly the same trigger definitions.
    sql = files("aberration_core").joinpath("db/evidence_clock.sql").read_text()
    # asyncpg prepares one statement at a time; explicit boundaries preserve
    # the semicolons inside the PL/pgSQL functions.
    for statement in sql.split("-- statement\n"):
        connection.exec_driver_sql(statement)
