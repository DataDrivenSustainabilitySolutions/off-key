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
    "015_detector_evidence.sql",
    "016_pipeline_run_events.sql",
    "017_detector_inputs.sql",
    "018_member_favorites.sql",
    "019_dojo_datasets.sql",
    "020_dojo_runs.sql",
    "021_member_roles.sql",
    "022_dojo_labels.sql",
    "023_device_favorites.sql",
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
        "monitoring_pipeline_run_events",
        "monitoring_pipeline_activations",
        "monitoring_pipeline_runs",
        "monitoring_pipeline_revisions",
        "monitoring_pipelines",
    ):
        connection.execute(text(f"DROP TABLE {name}"))


def restore_retired_schema(connection):
    """Recreate schema every pre-014 database carries and migrations 014-021 drop."""
    connection.execute(text("CREATE TABLE model_registry (id serial PRIMARY KEY)"))
    restore_entity_favorites(connection)
    restore_role_enum(connection)
    connection.execute(
        text("ALTER TABLE services ADD COLUMN stateful_set_name text UNIQUE")
    )
    # The pre-ledger ORM named the telemetry primary key after its identical
    # unique constraint; production databases still carry that name.
    primary_key = connection.scalar(
        text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'telemetry'::regclass AND contype = 'p'"
        )
    )
    connection.execute(
        text(
            f"ALTER TABLE telemetry RENAME CONSTRAINT {primary_key} "
            "TO uq_telemetry_entry"
        )
    )


def restore_entity_favorites(connection):
    """Swap member favorites for the entity-only table every pre-018 database has."""
    connection.execute(text("DROP TABLE member_favorites"))
    connection.execute(
        text("""
        CREATE TABLE favorites (
            favorite_id serial PRIMARY KEY,
            charger_id text NOT NULL REFERENCES chargers(charger_id),
            user_id integer NOT NULL REFERENCES users(id)
        );
        CREATE INDEX ix_favorite_user_charger ON favorites (user_id, charger_id)
    """)
    )


def restore_role_enum(connection):
    """Swap roles for the user/admin enum every pre-020 database has."""
    connection.execute(
        text("""
        ALTER TABLE users DROP CONSTRAINT users_role_fkey;
        DROP TABLE member_roles;
        CREATE TYPE roleenum AS ENUM ('user', 'admin');
        ALTER TABLE users ALTER COLUMN role TYPE roleenum USING role::roleenum
    """)
    )
