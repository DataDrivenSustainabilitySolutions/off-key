"""Upgrade real historical identities without losing history or evidence."""

import pytest
from aberration_core.db.migrate import (
    LEDGER,
    LEGACY_LEDGER,
    apply_migrations,
    migration_files,
    migration_status,
)
from sqlalchemy import text


def legacy_database(connection):
    migrations = migration_files()
    migrations.pop("026_aberration_identity.sql")
    apply_migrations(connection, migrations)
    connection.exec_driver_sql(migrations["025_evidence_cursor.sql"])
    connection.execute(text(f"ALTER TABLE {LEDGER} RENAME TO {LEGACY_LEDGER}"))
    connection.execute(
        text(
            f"ALTER TABLE {LEGACY_LEDGER} RENAME CONSTRAINT {LEDGER}_pkey "
            f"TO {LEGACY_LEDGER}_pkey"
        )
    )


def test_upgrade_preserves_ledger_and_evidence_clock(disposable_database):
    with disposable_database.begin() as connection:
        legacy_database(connection)
        original = connection.execute(
            text(f"SELECT version, checksum, applied_at FROM {LEGACY_LEDGER}")
        ).all()
        watermark = connection.scalar(
            text("SELECT last_created FROM monitoring_evidence_clock WHERE id = 1")
        )
        assert migration_status(connection)["pending"] == [
            "026_aberration_identity.sql"
        ]
        # Read-only preflight must not rename the ledger.
        assert connection.scalar(text(f"SELECT to_regclass('{LEGACY_LEDGER}')"))
        result = apply_migrations(connection)
        assert result["applied"] == ["026_aberration_identity.sql"]
        assert not connection.scalar(text(f"SELECT to_regclass('{LEGACY_LEDGER}')"))
        assert set(original) <= set(
            connection.execute(
                text(f"SELECT version, checksum, applied_at FROM {LEDGER}")
            ).all()
        )
        assert (
            connection.scalar(
                text("SELECT last_created FROM monitoring_evidence_clock WHERE id = 1")
            )
            == watermark
        )
        assert not connection.scalar(
            text(
                "SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
                "ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'public' AND p.proname LIKE 'off_key_%'"
            )
        )
        assert apply_migrations(connection)["applied"] == []


def test_ambiguous_ledgers_are_rejected(disposable_database):
    with disposable_database.begin() as connection:
        legacy_database(connection)
        connection.execute(text(f"CREATE TABLE {LEDGER} (version text)"))
        with pytest.raises(ValueError, match="Both schema ledgers"):
            migration_status(connection)


def test_changed_historical_checksum_is_rejected(disposable_database):
    with disposable_database.begin() as connection:
        legacy_database(connection)
        connection.execute(text(f"UPDATE {LEGACY_LEDGER} SET checksum = 'changed'"))
        with pytest.raises(ValueError, match="history differs"):
            apply_migrations(connection)
