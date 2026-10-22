"""Build truthful pre-pipeline database fixtures for historical upgrades."""

from sqlalchemy import text

# The migration history tests replay, in order. A new migration is added here
# deliberately; test_migration_history_is_the_expected_sequence catches drift.
EXPECTED_MIGRATIONS = (
    "001_membership.sql",
    "002_monitor_stop_intent.sql",
    "003_deployment_maintenance.sql",
    "004_system_catalogue.sql",
    "005_generic_runtime.sql",
    "006_remembered_sessions.sql",
    "007_monitor_anomaly_identity.sql",
    "008_radar_runtime_checkpoints.sql",
    "009_radar_lifecycle_intent.sql",
    "010_monitoring_pipelines.sql",
    "011_case_insensitive_emails.sql",
    "012_remembered_session_rotation.sql",
    "013_pipeline_templates.sql",
    "014_drop_unread_schema.sql",
)


def migrations_from(first: str) -> list[str]:
    """The expected migrations from ``first`` to the newest, in order."""
    return list(EXPECTED_MIGRATIONS[EXPECTED_MIGRATIONS.index(first) :])


def rewind_ledger(connection, first_pending: str | None = None) -> None:
    """Forget the ledger from ``first_pending`` on, or the whole ledger.

    Without a version the database looks like one created before the ledger.
    """
    if first_pending is None:
        connection.execute(text("DROP TABLE off_key_schema_migrations"))
    else:
        connection.execute(
            text("DELETE FROM off_key_schema_migrations WHERE version >= :version"),
            {"version": first_pending},
        )


def remove_pipeline_schema(connection):
    """Remove future tables before replaying a pre-010 migration history.

    Erasing only the ledger while retaining these tables represents a corrupt
    database, not the older release each adoption test intends to exercise.
    """
    for name in (
        "monitoring_pipeline_activations",
        "monitoring_pipeline_runs",
        "monitoring_pipeline_revisions",
        "monitoring_pipelines",
    ):
        connection.execute(text(f"DROP TABLE {name}"))


def restore_retired_schema(connection):
    """Recreate schema every pre-014 database carries and migration 014 drops."""
    connection.execute(text("CREATE TABLE model_registry (id serial PRIMARY KEY)"))
    connection.execute(
        text("ALTER TABLE services ADD COLUMN stateful_set_name text UNIQUE")
    )
