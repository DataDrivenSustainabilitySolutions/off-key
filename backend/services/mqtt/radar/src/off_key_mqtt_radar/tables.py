"""RADAR's view of the shared tables, built from core's table contracts.

The tables are bound to RADAR's own metadata: importing core ORM models would
initialize the full application Settings in RADAR-only containers.
"""

from off_key_core.db.table_contracts import (
    anomalies_table,
    anomaly_identity_table,
    monitoring_evidence_table,
    radar_runtime_checkpoints_table,
)
from sqlalchemy.schema import MetaData

_metadata = MetaData()
ANOMALY_TABLE = anomalies_table(_metadata)
ANOMALY_IDENTITY_TABLE = anomaly_identity_table(_metadata)
MONITORING_EVIDENCE_TABLE = monitoring_evidence_table(_metadata)
RUNTIME_CHECKPOINT_TABLE = radar_runtime_checkpoints_table(_metadata)
