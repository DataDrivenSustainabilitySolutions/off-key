"""Pin the migration ledger so a byte change cannot strand deployed databases.

``migration_status`` refuses to start when an applied migration's checksum
differs from the release. Fresh test databases always compute the current
checksum, so only a deploy onto real data would notice an edited migration.
"""

from off_key_core.db.migrate import BASELINE, migration_checksum, migration_files

APPLIED_CHECKSUMS = {
    BASELINE: "dcd5666da2ed1466cf0b4ece3cf02f05c2dcb0180bfa62e603e28f85863a88ab",
    "001_proposal_rationale.sql": (
        "6097980cc9eb9f8d0d1b5ec6557f9b89a4d6004c15afe7563f70585e4a6fafcd"
    ),
    "002_dojo_agent_owner.sql": (
        "3f632463ce68189351f00ab9618febd51457abe28b732cff658657412787af6b"
    ),
    "003_session_persistence.sql": (
        "1b812d875f62d022c530010b3d8dc9b12354c70b41195c9bda2033ca7721872e"
    ),
    "004_dojo_pending_labels.sql": (
        "ea43cb766cc073b55a192932cc7d66d2e75cf12c2ab0e1d299f27b80a29c38c9"
    ),
    "005_dojo_benchmark_origin.sql": (
        "1990dc1fcfa9406218ee9e468bfdab5a84ede89492b4ccf203c85b5909772b09"
    ),
    "006_dojo_suites.sql": (
        "728e3266cd58f065ec08412c2ddfefe8871f31b0d56d45cd847827b2e0ad98d8"
    ),
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
