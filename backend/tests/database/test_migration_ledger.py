"""Pin the migration ledger so a byte change cannot strand deployed databases.

``migration_status`` refuses to start when an applied migration's checksum
differs from the release. Fresh test databases always compute the current
checksum, so only a deploy onto real data would notice an edited migration.
"""

from off_key_core.db.migrate import BASELINE, migration_checksum, migration_files

APPLIED_CHECKSUMS = {
    BASELINE: "dcd5666da2ed1466cf0b4ece3cf02f05c2dcb0180bfa62e603e28f85863a88ab",
}


def test_the_baseline_comes_first():
    assert next(iter(migration_files())) == BASELINE


def test_released_migrations_keep_their_applied_checksums():
    migrations = migration_files()

    assert list(migrations) == list(APPLIED_CHECKSUMS), (
        "Add a pin for every new migration; never rename or remove a released one"
    )
    changed = [
        version
        for version, sql in migrations.items()
        if migration_checksum(sql) != APPLIED_CHECKSUMS[version]
    ]
    assert not changed, (
        f"{changed} changed after release. Every database that applied them would "
        "refuse to start ('Applied migration history differs from this release'). "
        "Revert the edit and add a new migration instead."
    )
