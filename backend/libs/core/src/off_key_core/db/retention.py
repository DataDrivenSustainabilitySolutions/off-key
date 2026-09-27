"""Reconcile managed TimescaleDB policies and report their persisted state."""

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_retention_days
from ..config.logs import logger
from ..schemas.storage import RetentionPolicyStatus, StorageStatus

RETENTION_TABLES = ("telemetry", "monitoring_evidence")


def reconcile_retention_policies(connection: Connection) -> None:
    """Apply the configured duration without replacing existing jobs or schedules."""
    drop_after = f"{get_retention_days()} days"
    for table in RETENTION_TABLES:
        job = (
            connection.execute(
                text(
                    """
                    SELECT job_id, scheduled, config,
                           CAST(config ->> 'drop_after' AS interval)
                               = CAST(CAST(:drop_after AS text) AS interval) AS matches
                    FROM timescaledb_information.jobs
                    WHERE hypertable_schema = 'public'
                      AND hypertable_name = :table AND proc_name = 'policy_retention'
                    """
                ),
                {"table": table, "drop_after": drop_after},
            )
            .mappings()
            .one_or_none()
        )
        if job is None:
            connection.execute(
                text(
                    """
                    SELECT add_retention_policy(
                        to_regclass(:table), CAST(CAST(:drop_after AS text) AS interval)
                    )
                    """
                ),
                {"table": f"public.{table}", "drop_after": drop_after},
            )
        elif (
            not job["matches"]
            or not job["scheduled"]
            or "drop_created_before" in job["config"]
        ):
            connection.execute(
                text(
                    """
                    SELECT alter_job(
                        job_id,
                        config => (config - 'drop_created_before')
                            || jsonb_build_object(
                                'drop_after', CAST(:drop_after AS text)
                            ),
                        scheduled => true
                    )
                    FROM timescaledb_information.jobs WHERE job_id = :job_id
                    """
                ),
                {"job_id": job["job_id"], "drop_after": drop_after},
            )
        else:
            continue
        logger.info("Retention policy applied for %s: %s", table, drop_after)


async def read_storage_status(session: AsyncSession) -> StorageStatus:
    """Read policies from TimescaleDB, never infer them from process settings."""
    rows = await session.execute(
        text(
            """
            SELECT hypertable_name,
                   EXTRACT(EPOCH FROM CAST(config ->> 'drop_after' AS interval))
                       / 86400 AS retention_days,
                   scheduled
            FROM timescaledb_information.jobs
            WHERE hypertable_schema = 'public' AND proc_name = 'policy_retention'
              AND hypertable_name = ANY(CAST(:tables AS text[]))
            """
        ),
        {"tables": list(RETENTION_TABLES)},
    )
    policies = {row["hypertable_name"]: row for row in rows.mappings()}
    size = await session.scalar(text("SELECT pg_database_size(current_database())"))
    return StorageStatus(
        database_size_bytes=size,
        retention_policies=[
            RetentionPolicyStatus(
                table=table,
                retention_days=policies[table]["retention_days"],
                scheduled=policies[table]["scheduled"],
            )
            if table in policies
            else RetentionPolicyStatus(table=table)
            for table in RETENTION_TABLES
        ],
        checked_at=datetime.now(UTC),
    )
