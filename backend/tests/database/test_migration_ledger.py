"""Pin the migration ledger so a byte change cannot strand deployed databases.

``migration_status`` refuses to start when an applied migration's checksum
differs from the release. Fresh test databases always compute the current
checksum, so only a deploy onto real data would notice an edited migration, or
an edited converter module that migration 005 hashes with its SQL.
"""

from off_key_core.db.migrate import (
    BASELINE_TABLES,
    PRE_LEDGER_TABLES,
    SYSTEM_TABLES,
    migration_checksum,
    migration_files,
)
from off_key_core.db.models import Base

APPLIED_CHECKSUMS = {
    "001_membership.sql": (
        "017d037e8fcd033946d1ebe91529c10493097ca617ebb17f37083e6c2b74c377"
    ),
    "002_monitor_stop_intent.sql": (
        "7585cbeb894e282ddb5809c43a3eaf6e106948ab3c14ae8955702e7edd97ca8a"
    ),
    "003_deployment_maintenance.sql": (
        "064b3cbb0a6d74ebc2b70f90ea8956d44a995d4ea2b990ed83d75d914cd616ea"
    ),
    "004_system_catalogue.sql": (
        "99369f577d36abe99dfa2a0a6cf14c01f9864ddf13424d39e4ef698ab5ede033"
    ),
    # Also hashes db/catalogue_upgrade.py, catalogue_v1.py and
    # catalogue_v1_models.py, which are therefore frozen byte for byte.
    "005_generic_runtime.sql": (
        "74affc68cde2fb499b6207b262d05e398c8de004ae84979ec285a93d6c5b3f92"
    ),
    "006_remembered_sessions.sql": (
        "220052e074ce16ef27e5e02dadfdd96e661ddc5c0bde11f551fb13311b823580"
    ),
    "007_monitor_anomaly_identity.sql": (
        "d47b7ef4c7ca320d19caeb726980d70640e124037b8217e3b988d122bc5c1cfd"
    ),
    "008_radar_runtime_checkpoints.sql": (
        "83269bf04a8053d59198e6d093d81edcfee61c53d72975cefe9cc50d31d3e75e"
    ),
    "009_radar_lifecycle_intent.sql": (
        "deba4beeee1caceb1df6444e71fa1d65ca270908c3e8f24732ae0b0c2ab007cb"
    ),
    "010_monitoring_pipelines.sql": (
        "0ed90a0b4002d1cd641a6baf6599bd01902e23027102aa886d66ee910e7d2b7d"
    ),
    "011_case_insensitive_emails.sql": (
        "5701f50febdb3cfe4b1cd6b37e48c106bef3b42779b867e122ef5c31c931475a"
    ),
    "012_remembered_session_rotation.sql": (
        "87cb81bb70d34348f0249062e7d790fa6ed715284210d089cfa7ef35b646f850"
    ),
    "013_pipeline_templates.sql": (
        "5f201c44247726ac28fcda3b3c372ad7fa956f10d9dc1ce3b2099e1e5aad22ca"
    ),
    "014_drop_unread_schema.sql": (
        "e2f93eb810b317ffd9be6e2a64d13f8ed277c3d5f62d966669641e79ff4706f0"
    ),
    "015_detector_evidence.sql": (
        "6d4f0ac47f069e8c61dc292b921f0bf3487a05dbdb06e63c7744ee5bb785fc99"
    ),
    "016_pipeline_run_events.sql": (
        "43a86fcf11a428b24cde3590cdfa86d311281883d5d43784a254df011a2b9fdd"
    ),
    "017_detector_inputs.sql": (
        "bb49f11f5966ec132584ed56689a17bef52a1edf13416308e753d1d8ef664cfb"
    ),
    "018_member_favorites.sql": (
        "6bdac3306802ce962fb20a455856160de8e9d0d5868394cfd7668565d4c06273"
    ),
    "019_dojo_datasets.sql": (
        "02d1e64607ae046c043cf2e0038e63cf2add1095a5d2d57cb6bd4200efb8bda2"
    ),
    "020_dojo_runs.sql": (
        "e9fa42bac7e1ce10982daa6b4f7cbd182fb57cb680b72cf4e29196a0a096801a"
    ),
}

# Tables added after the ledger, by the migration that introduced them. A new
# ORM table must be classified here before adoption can be reasoned about.
LEDGER_TABLES = {
    "004_system_catalogue.sql": SYSTEM_TABLES,
    "006_remembered_sessions.sql": {"remembered_sessions"},
    "008_radar_runtime_checkpoints.sql": {"radar_runtime_checkpoints"},
    "010_monitoring_pipelines.sql": {
        "monitoring_pipelines",
        "monitoring_pipeline_revisions",
        "monitoring_pipeline_runs",
        "monitoring_pipeline_activations",
    },
    "016_pipeline_run_events.sql": {"monitoring_pipeline_run_events"},
    "018_member_favorites.sql": {"member_favorites"},
    "019_dojo_datasets.sql": {
        "dojo_datasets",
        "dojo_dataset_series",
        "dojo_dataset_points",
    },
    "020_dojo_runs.sql": {"dojo_runs", "dojo_run_results"},
}
# Pre-ledger tables a later migration dropped.
RETIRED_TABLES = {
    "014_drop_unread_schema.sql": {"model_registry"},
    "018_member_favorites.sql": {"favorites"},
}


def test_released_migrations_keep_their_applied_checksums():
    migrations = migration_files()

    assert list(migrations) == list(APPLIED_CHECKSUMS), (
        "Add a pin for every new migration; never rename or remove a released one"
    )
    changed = [
        version
        for version, sql in migrations.items()
        if migration_checksum(version, sql) != APPLIED_CHECKSUMS[version]
    ]
    assert not changed, (
        f"{changed} changed after release. Every database that applied them would "
        "refuse to start ('Applied migration history differs from this release'). "
        "Revert the edit and add a new migration instead."
    )


def test_every_orm_table_is_pre_ledger_or_owned_by_a_migration():
    owned = set().union(*LEDGER_TABLES.values())

    assert not PRE_LEDGER_TABLES & owned
    retired = set().union(*RETIRED_TABLES.values())
    assert retired <= PRE_LEDGER_TABLES
    assert set(Base.metadata.tables) == (PRE_LEDGER_TABLES | owned) - retired
    assert PRE_LEDGER_TABLES - {"deployment_maintenance"} == BASELINE_TABLES
