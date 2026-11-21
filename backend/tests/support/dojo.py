"""The tables Dojo, proposal and agent tests share, created in one call."""

from off_key_core.db.models import (
    Agent,
    Base,
    DeploymentMaintenance,
    DojoDataset,
    DojoLabel,
    DojoPendingLabel,
    DojoPoint,
    DojoRun,
    DojoRunResult,
    DojoSeries,
    DojoStudy,
    DojoSuite,
    DojoSuiteDataset,
    MonitorEventRecord,
    MonitoringPipeline,
    PipelineProposal,
    PipelineRevision,
)

# Every table a Dojo workflow reaches. A new Dojo table goes here once, rather
# than into each test module's own list.
DOJO_TABLES = (
    DeploymentMaintenance,
    Agent,
    DojoDataset,
    DojoSeries,
    DojoPoint,
    DojoLabel,
    DojoPendingLabel,
    DojoSuite,
    DojoSuiteDataset,
    DojoStudy,
    DojoRun,
    DojoRunResult,
    MonitoringPipeline,
    PipelineRevision,
    PipelineProposal,
    MonitorEventRecord,
)


def create_dojo_tables(connection):
    """Create DOJO_TABLES in foreign-key order; for ``connection.run_sync``."""
    Base.metadata.create_all(
        connection, tables=[model.__table__ for model in DOJO_TABLES]
    )
