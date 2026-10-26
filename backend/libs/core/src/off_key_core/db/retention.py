"""Reconcile managed TimescaleDB policies and report their persisted state."""

import json
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_telemetry_settings
from ..config.logs import logger
from ..schemas.storage import RetentionPolicyStatus, StorageStatus

RETENTION_TABLES = ("telemetry", "monitoring_evidence")
# Finer chunks let retention and the storage cap release space a day at a time.
CHUNK_INTERVAL = "1 day"
ANOMALY_RETENTION_PROC = "off_key_anomaly_retention"
ANOMALY_RETENTION_SCHEDULE = "1 hour"
STORAGE_CAP_PROC = "off_key_storage_cap"
STORAGE_CAP_SCHEDULE = "15 minutes"

# anomaly_identity references anomalies, which blocks drop_chunks, so anomaly
# retention deletes rows and lets the foreign key cascade.
_PROCEDURES = (
    f"""
    CREATE OR REPLACE PROCEDURE public.{ANOMALY_RETENTION_PROC}(
        job_id integer, config jsonb
    ) LANGUAGE plpgsql AS $$
    BEGIN
        DELETE FROM public.anomalies
        WHERE timestamp < now() - CAST(config ->> 'drop_after' AS interval);
    END;
    $$
    """,
    f"""
    CREATE OR REPLACE PROCEDURE public.{STORAGE_CAP_PROC}(
        job_id integer, config jsonb
    ) LANGUAGE plpgsql AS $$
    DECLARE
        max_bytes bigint := CAST(config ->> 'max_bytes' AS bigint);
        tables text[] := ARRAY(SELECT jsonb_array_elements_text(config -> 'tables'));
        total bigint;
        oldest record;
    BEGIN
        LOOP
            SELECT COALESCE(sum(hypertable_size(to_regclass('public.' || name))), 0)
            INTO total FROM unnest(tables) AS name;
            EXIT WHEN total <= max_bytes;
            -- Only chunks that ended in the past; current data is never dropped.
            SELECT hypertable_name, chunk_name, range_end INTO oldest
            FROM timescaledb_information.chunks
            WHERE hypertable_schema = 'public' AND hypertable_name = ANY(tables)
              AND range_end <= now()
            ORDER BY range_end, hypertable_name
            LIMIT 1;
            IF NOT FOUND THEN
                RAISE WARNING 'off-key storage cap: % bytes used, cap % bytes, '
                    'no completed chunks left to drop', total, max_bytes;
                EXIT;
            END IF;
            PERFORM drop_chunks(
                to_regclass('public.' || oldest.hypertable_name),
                older_than => oldest.range_end
            );
            RAISE WARNING 'off-key storage cap: % bytes used, cap % bytes, '
                'dropped % data before %',
                total, max_bytes, oldest.hypertable_name, oldest.range_end;
        END LOOP;
    END;
    $$
    """,
)


def _find_job(connection: Connection, proc_name: str):
    return (
        connection.execute(
            text(
                """
                SELECT job_id, scheduled, config FROM timescaledb_information.jobs
                WHERE proc_schema = 'public' AND proc_name = :proc_name
                ORDER BY job_id LIMIT 1
                """
            ),
            {"proc_name": proc_name},
        )
        .mappings()
        .one_or_none()
    )


def _reconcile_custom_job(
    connection: Connection, proc_name: str, schedule: str, config: dict | None
) -> None:
    """Keep one job per procedure; keep operator schedules, enforce the config."""
    job = _find_job(connection, proc_name)
    if config is None:
        if job is not None:
            connection.execute(
                text("SELECT delete_job(:job_id)"), {"job_id": job["job_id"]}
            )
            logger.info("Removed %s job", proc_name)
        return
    if job is None:
        connection.execute(
            text(
                """
                SELECT add_job(
                    CAST(CAST(:proc AS text) AS regproc),
                    CAST(CAST(:schedule AS text) AS interval),
                    config => CAST(CAST(:config AS text) AS jsonb)
                )
                """
            ),
            {
                "proc": f"public.{proc_name}",
                "schedule": schedule,
                "config": json.dumps(config),
            },
        )
    elif job["config"] != config or not job["scheduled"]:
        connection.execute(
            text(
                """
                SELECT alter_job(
                    :job_id,
                    config => CAST(CAST(:config AS text) AS jsonb),
                    scheduled => true
                )
                """
            ),
            {"job_id": job["job_id"], "config": json.dumps(config)},
        )
    else:
        return
    logger.info("Applied %s job: %s", proc_name, config)


def _reconcile_chunk_interval(connection: Connection, table: str) -> None:
    """Only future chunks change; existing chunks keep their original span."""
    current = connection.scalar(
        text(
            """
            SELECT time_interval = CAST(CAST(:interval AS text) AS interval)
            FROM timescaledb_information.dimensions
            WHERE hypertable_schema = 'public' AND hypertable_name = :table
              AND dimension_number = 1
            """
        ),
        {"table": table, "interval": CHUNK_INTERVAL},
    )
    if not current:
        connection.execute(
            text(
                "SELECT set_chunk_time_interval("
                "to_regclass(:table), CAST(CAST(:interval AS text) AS interval))"
            ),
            {"table": f"public.{table}", "interval": CHUNK_INTERVAL},
        )


def reconcile_retention_policies(connection: Connection) -> None:
    """Apply the configured duration without replacing existing jobs or schedules."""
    settings = get_telemetry_settings()
    drop_after = f"{settings.retention_days} days"
    for table in RETENTION_TABLES:
        _reconcile_chunk_interval(connection, table)
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

    for procedure in _PROCEDURES:
        connection.execute(text(procedure))
    _reconcile_custom_job(
        connection,
        ANOMALY_RETENTION_PROC,
        ANOMALY_RETENTION_SCHEDULE,
        {"drop_after": drop_after},
    )
    cap = settings.storage_cap_bytes
    _reconcile_custom_job(
        connection,
        STORAGE_CAP_PROC,
        STORAGE_CAP_SCHEDULE,
        None if cap is None else {"max_bytes": cap, "tables": list(RETENTION_TABLES)},
    )


async def read_storage_status(session: AsyncSession) -> StorageStatus:
    """Read policies from TimescaleDB, never infer them from process settings."""
    rows = await session.execute(
        text(
            """
            SELECT CASE WHEN proc_name = :anomaly_proc THEN 'anomalies'
                        ELSE hypertable_name END AS table_name,
                   EXTRACT(EPOCH FROM CAST(config ->> 'drop_after' AS interval))
                       / 86400 AS retention_days,
                   scheduled
            FROM timescaledb_information.jobs
            WHERE (hypertable_schema = 'public' AND proc_name = 'policy_retention'
                   AND hypertable_name = ANY(CAST(:tables AS text[])))
               OR (proc_schema = 'public' AND proc_name = :anomaly_proc)
            """
        ),
        {"tables": list(RETENTION_TABLES), "anomaly_proc": ANOMALY_RETENTION_PROC},
    )
    policies = {row["table_name"]: row for row in rows.mappings()}
    cap = (
        (
            await session.execute(
                text(
                    """
                    SELECT CAST(config ->> 'max_bytes' AS bigint) AS max_bytes,
                           scheduled
                    FROM timescaledb_information.jobs
                    WHERE proc_schema = 'public' AND proc_name = :cap_proc
                    ORDER BY job_id LIMIT 1
                    """
                ),
                {"cap_proc": STORAGE_CAP_PROC},
            )
        )
        .mappings()
        .one_or_none()
    )
    size = await session.scalar(text("SELECT pg_database_size(current_database())"))
    capped_size = await session.scalar(
        text(
            """
            SELECT COALESCE(sum(hypertable_size(to_regclass('public.' || name))), 0)
            FROM unnest(CAST(:tables AS text[])) AS name
            """
        ),
        {"tables": list(RETENTION_TABLES)},
    )
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
            for table in (*RETENTION_TABLES, "anomalies")
        ],
        storage_cap_bytes=None if cap is None else cap["max_bytes"],
        storage_cap_scheduled=False if cap is None else cap["scheduled"],
        capped_size_bytes=capped_size,
        checked_at=datetime.now(UTC),
    )
