"""Bootstrap the supported development schema without upgrading historical data."""

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
    inspect,
    text,
)
from sqlalchemy.engine import Connection

from .models import Base


def validate_existing_schema(connection: Connection) -> None:
    """Reject obsolete table shapes before executing any bootstrap DDL."""
    inspector = inspect(connection)
    existing = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            continue
        columns = {
            column["name"]: column for column in inspector.get_columns(table.name)
        }
        expected = {column.name for column in table.columns}
        compatible = set(columns) == expected and all(
            columns[column.name]["nullable"] == column.nullable
            and isinstance(columns[column.name]["type"], type(column.type))
            and getattr(columns[column.name]["type"], "timezone", None)
            == getattr(column.type, "timezone", None)
            for column in table.columns
        )
        primary_key = inspector.get_pk_constraint(table.name)
        compatible = compatible and primary_key["constrained_columns"] == [
            column.name for column in table.primary_key.columns
        ]
        constraint_names = {
            constraint["name"]
            for constraint in (
                inspector.get_check_constraints(table.name)
                + inspector.get_foreign_keys(table.name)
                + inspector.get_unique_constraints(table.name)
            )
        }
        # PostgreSQL can fold a UNIQUE constraint identical to the PK into the PK.
        constraint_names.add(primary_key["name"])
        compatible = compatible and all(
            constraint.name in constraint_names
            for constraint in table.constraints
            if isinstance(
                constraint, CheckConstraint | ForeignKeyConstraint | UniqueConstraint
            )
            and constraint.name
        )
        if not compatible:
            raise RuntimeError(
                f"Unsupported schema for table {table.name!r}. "
                "Automatic schema upgrades are not supported. "
                "Use a fresh development database; existing data was not modified."
            )


def bootstrap_schema(connection: Connection) -> None:
    """Create current tables and install their required database behavior."""
    validate_existing_schema(connection)
    connection.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    Base.metadata.create_all(connection)
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            index.create(connection, checkfirst=True)
    connection.execute(
        text(
            """
            CREATE OR REPLACE FUNCTION off_key_sync_anomaly_identity()
            RETURNS TRIGGER AS $$
            BEGIN
                INSERT INTO anomaly_identity (charger_id, timestamp, telemetry_type)
                VALUES (NEW.charger_id, NEW.timestamp, NEW.telemetry_type)
                ON CONFLICT (charger_id, timestamp, telemetry_type) DO NOTHING;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE OR REPLACE TRIGGER trg_anomaly_identity_sync
            AFTER INSERT ON anomalies FOR EACH ROW
            EXECUTE FUNCTION off_key_sync_anomaly_identity();
            """
        )
    )
