"""Build truthful pre-pipeline database fixtures for historical upgrades."""

from sqlalchemy import text


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
