"""Apply reviewed SQL migrations before the target application starts."""

import argparse
import json
from hashlib import sha256
from importlib.resources import files

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from .base import get_engine
from .locks import MIGRATION_LOCK
from .models import Base
from .schema import bootstrap_schema

LEDGER = "off_key_schema_migrations"
# The schema the ORM bootstrap creates. Every supported database records it
# first; a ledger without it belongs to the history this release retired.
BASELINE = "000_baseline.sql"


class RetiredSchemaError(ValueError):
    """The database predates the schema baseline and must be reset."""


def migration_files() -> dict[str, str]:
    directory = files("off_key_core").joinpath("db/migrations")
    return {
        path.name: path.read_text()
        for path in sorted(directory.iterdir(), key=lambda path: path.name)
        if path.name.endswith(".sql")
    }


def migration_checksum(sql: str) -> str:
    return sha256(sql.encode()).hexdigest()


def migration_status(
    connection: Connection, migrations: dict[str, str] | None = None
) -> dict:
    """Pending migrations of a baseline database, or a fresh one's whole set.

    Only an empty database or one that recorded the baseline is accepted. Any
    other database predates the baseline and is refused before it is changed.
    """
    migrations = migration_files() if migrations is None else migrations
    tables = set(inspect(connection).get_table_names())
    rows = {}
    if LEDGER in tables:
        rows = dict(
            connection.execute(text(f"SELECT version, checksum FROM {LEDGER}")).all()
        )
    if BASELINE not in rows:
        if tables - {LEDGER} or rows:
            raise RetiredSchemaError(
                "This database predates the schema baseline; reset it to an "
                "empty database before deploying this release"
            )
        return {"pending": list(migrations), "applied": [], "fresh": True}
    for version, checksum in rows.items():
        if version not in migrations or checksum != migration_checksum(
            migrations[version]
        ):
            raise ValueError("Applied migration history differs from this release")
    applied = [version for version in migrations if version in rows]
    if applied != list(migrations)[: len(applied)]:
        raise ValueError("Applied migrations are not an ordered prefix of this release")
    if not tables.intersection(Base.metadata.tables):
        raise ValueError("The migration ledger records a schema that is missing")
    return {
        "pending": [version for version in migrations if version not in applied],
        "applied": applied,
        "fresh": False,
    }


def verify_migrations(
    connection: Connection, migrations: dict[str, str] | None = None
) -> dict:
    """Require the complete checksum ledger without changing the schema."""
    if not inspect(connection).has_table(LEDGER):
        raise ValueError("The verified migration ledger is missing")
    status = migration_status(connection, migrations)
    if status["pending"] or status["fresh"]:
        raise ValueError("The target schema has not been fully applied")
    return status


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
        # An empty database gets the current schema directly; every migration
        # it already contains is recorded without running.
        bootstrap_schema(connection)
    for version, sql in migrations.items():
        if version not in status["pending"]:
            continue
        if not status["fresh"]:
            connection.exec_driver_sql(sql)
        connection.execute(
            text(f"""
            INSERT INTO {LEDGER} (version, checksum) VALUES (:version, :checksum)
        """),
            {"version": version, "checksum": migration_checksum(sql)},
        )
    bootstrap_schema(connection)
    return {"applied": status["pending"], "fresh": status["fresh"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "apply", "verify"])
    action = parser.parse_args().action
    try:
        with get_engine().begin() as connection:
            result = {
                "status": migration_status,
                "apply": apply_migrations,
                "verify": verify_migrations,
            }[action](connection)
        print(json.dumps(result))
    except RetiredSchemaError as error:
        # Our own message, without SQL or data: the deploy shows it as the reason.
        print(json.dumps({"error": str(error), "reset_required": True}))
        raise SystemExit(1) from None
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
