"""Dojo datasets: frozen copies of time series, independent of live telemetry.

A dataset never points into ``telemetry``. Retention, catalogue edits and
recording changes therefore leave it untouched, so a comparison run on it can
be repeated later with the same numbers.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def document():
    return JSON().with_variant(JSONB(), "postgresql")


class DojoDataset(Base):
    __tablename__ = "dojo_datasets"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 'csv' for an upload, 'history' for a copy of recorded readings.
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    # Where the points came from: file name and layout, or readings and window.
    source: Mapped[Any] = mapped_column(document(), nullable=False, default=dict)
    # A removed member's datasets stay with the workspace.
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    point_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        CheckConstraint("origin IN ('csv', 'history')", name="ck_dojo_dataset_origin"),
    )


class DojoSeries(Base):
    """One named column of a dataset, such as one reading or one CSV column."""

    __tablename__ = "dojo_dataset_series"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        Text, ForeignKey("dojo_datasets.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The catalogue reading a copied series came from; suggests the live
    # reading when a design moves from the Dojo to Monitoring.
    reading_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    point_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    __table_args__ = (
        UniqueConstraint("dataset_id", "name", name="uq_dojo_series_name"),
        UniqueConstraint("dataset_id", "position", name="uq_dojo_series_position"),
    )


class DojoPoint(Base):
    """One value. Deliberately no foreign key to its series: a per-row check
    makes a five-million-value import several times slower. The dataset
    service deletes a dataset's points with it."""

    __tablename__ = "dojo_dataset_points"
    series_id: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    __table_args__ = (
        # One value per series and instant; also the ordered read path.
        PrimaryKeyConstraint("series_id", "timestamp", name="pk_dojo_point"),
    )
