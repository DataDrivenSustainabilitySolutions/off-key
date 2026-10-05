"""Apply reviewed SQL migrations before the target application starts."""

import argparse
import json
from hashlib import sha256
from importlib.resources import files

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from .base import get_engine
from .models import Base
from .schema import bootstrap_schema, validate_existing_schema

MIGRATION_LOCK = 73128004
LEDGER = "off_key_schema_migrations"


def migration_files() -> dict[str, str]:
    directory = files("off_key_core").joinpath("db/migrations")
    return {
        path.name: path.read_text()
        for path in sorted(directory.iterdir(), key=lambda path: path.name)
        if path.name.endswith(".sql")
    }


def adopted_versions(connection: Connection, migrations: dict[str, str]) -> list[str]:
    """Adopt only the verified pre-integration schema or a fresh current schema."""
    existing = set(inspect(connection).get_table_names())
    application_tables = set(Base.metadata.tables)
    if not existing.intersection(application_tables):
        if existing - {LEDGER}:
            raise ValueError("Cannot initialize a database containing unknown tables")
        return []
    if application_tables <= existing:
        validate_existing_schema(connection)
        return [
            "001_membership.sql",
            "002_monitor_stop_intent.sql",
            "003_deployment_maintenance.sql",
        ]
    baseline = [
        table
        for table in Base.metadata.sorted_tables
        if table.name != "deployment_maintenance"
    ]
    if not {table.name for table in baseline} <= existing:
        raise ValueError("A reviewed baseline is required for this database")
    validate_existing_schema(
        connection, tables=baseline, excluded_columns={"services": {"launch_config"}}
    )
    return ["001_membership.sql", "002_monitor_stop_intent.sql"]


def migration_status(
    connection: Connection, migrations: dict[str, str] | None = None
) -> dict:
    migrations = migration_files() if migrations is None else migrations
    if inspect(connection).has_table(LEDGER):
        rows = dict(
            connection.execute(text(f"SELECT version, checksum FROM {LEDGER}")).all()
        )
        for version, checksum in rows.items():
            if (
                version not in migrations
                or checksum != sha256(migrations[version].encode()).hexdigest()
            ):
                raise ValueError("Applied migration history differs from this release")
        applied = [version for version in migrations if version in rows]
        if applied != list(migrations)[: len(applied)]:
            raise ValueError(
                "Applied migrations are not an ordered prefix of this release"
            )
    else:
        applied = adopted_versions(connection, migrations)
    fresh = not set(inspect(connection).get_table_names()).intersection(
        Base.metadata.tables
    )
    return {
        "pending": [version for version in migrations if version not in applied],
        "adopted": applied,
        "fresh": fresh,
    }


def apply_migrations(
    connection: Connection, migrations: dict[str, str] | None = None
) -> dict:
    """Caller owns one transaction covering DDL and its checksum records."""
    migrations = migration_files() if migrations is None else migrations
    if not connection.scalar(
        text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK}
    ):
        raise ValueError("Another database upgrade is in progress")
    connection.execute(text("SET LOCAL lock_timeout = '5s'"))
    connection.execute(text("SET LOCAL statement_timeout = '120s'"))
    status = migration_status(connection, migrations)
    connection.execute(
        text(f"""
        CREATE TABLE IF NOT EXISTS {LEDGER} (
            version text PRIMARY KEY, checksum text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    )
    if status["fresh"]:
        bootstrap_schema(connection)
    for version, sql in migrations.items():
        if not status["fresh"] and version in status["pending"]:
            connection.exec_driver_sql(sql)
        connection.execute(
            text(f"""
            INSERT INTO {LEDGER} (version, checksum) VALUES (:version, :checksum)
            ON CONFLICT (version) DO NOTHING
        """),
            {"version": version, "checksum": sha256(sql.encode()).hexdigest()},
        )
    bootstrap_schema(connection)
    return {"applied": status["pending"], "fresh": status["fresh"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "apply"])
    action = parser.parse_args().action
    try:
        with get_engine().begin() as connection:
            result = (
                migration_status(connection)
                if action == "status"
                else apply_migrations(connection)
            )
        print(json.dumps(result))
    except Exception:
        # SQL/driver errors can embed passwords and user data; keep them off CI logs.
        print(
            json.dumps(
                {"error": "Database migration failed; its transaction was rolled back."}
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
