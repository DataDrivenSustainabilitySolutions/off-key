"""RADAR workloads that pool workers lease from the database.

TACTIC and the API record what should run here; a replica of the RADAR pool
claims a row with a lease, runs it as a child process of its own, renews the
lease while the child lives and records how the child ended. Nothing reaches
Docker: a workload is a row, not a container.

``desired`` is the control plane's intent and ``state`` the pool's report:

- ``pending``: waiting for a worker (new, released, or restarting after a crash)
- ``running``: a worker holds the lease and runs the child
- ``complete`` / ``failed``: a one-off job ended, cleanly or not
- ``shutdown``: stopped on request; the row can be removed

A lease that is not renewed expires, and another worker may claim the row; a
worker that cannot renew stops its children before its leases can expire.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

WORKLOAD_KINDS = ("monitor", "preflight")
WORKLOAD_STATES = ("pending", "running", "complete", "failed", "shutdown")
# States after which no child runs for the row.
WORKLOAD_DONE = frozenset({"complete", "failed", "shutdown"})
# How many crashes a row remembers, newest first.
CRASH_HISTORY = 10
# Bytes of a one-off job's standard output kept for its report.
OUTPUT_LIMIT = 131072


class RadarWorkload(Base):
    __tablename__ = "radar_workloads"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    # Deterministic per owner (radar-<monitor> or preflight-<activation>), so a
    # retried request finds the row an earlier attempt created.
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    labels: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    # Only a worker running this exact image may claim the row.
    runtime: Mapped[str] = mapped_column(Text, nullable=False)
    module: Mapped[str] = mapped_column(Text, nullable=False)
    environment: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    memory_limit_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # A monitor restarts after a crash; a one-off job ends.
    restart: Mapped[bool] = mapped_column(nullable=False, default=False)
    desired: Mapped[str] = mapped_column(Text, nullable=False, default="run")
    state: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    worker_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # A crashed monitor waits before a worker claims it again.
    not_before: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    crashes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('monitor', 'preflight')", name="ck_radar_workloads_kind"
        ),
        CheckConstraint(
            "desired IN ('run', 'stop')", name="ck_radar_workloads_desired"
        ),
        CheckConstraint(
            "state IN ('pending', 'running', 'complete', 'failed', 'shutdown')",
            name="ck_radar_workloads_state",
        ),
        CheckConstraint(
            "(state = 'running') = (worker_id IS NOT NULL)",
            name="ck_radar_workloads_lease",
        ),
        Index("ix_radar_workloads_claim", "runtime", "state", "created_at"),
        Index("ix_radar_workloads_worker", "worker_id"),
    )
