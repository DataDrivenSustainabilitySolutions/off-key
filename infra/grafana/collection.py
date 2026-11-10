"""Follow upstream transport and persistence failures without inventing throughput."""

from .common import ERRORS, Dashboard, count, events, fields, level, series, services


def build():
    source = services("mqtt-proxy|tactic")
    broker = services("emqx-main|emqx-worker|broker-route")
    database = services("postgres|db-sync")
    writer = services("mqtt-proxy")
    collection_failures = (
        source + " |~ `Collection failed|System ingress interrupted; retrying`"
    )
    failed_writes = events(
        writer, "db_writer[.](batch_failed|shutdown_unwritten|record_rejected)"
    )
    retries = events(
        writer,
        "db_writer[.](batch_retry|batch_attempt_failed|batch_failed|batch_db_error|batch_unexpected_error)",
    )
    d = Dashboard(
        "collection", "Source collection, MQTT transport and persistence diagnostics."
    )
    d.note(
        "**Follow the data path:** source broker → TACTIC ingress → internal EMQX → MQTT proxy → "
        "TimescaleDB and accepted topics. Source retry logs, broker warnings and writer errors identify the failing hop.\n\n"
        "Collection counters and storage capacity are not exported to Loki. Successful write detail is DEBUG-only; "
        "these panels report **failure signals and slow-write samples**, not ingest throughput, data completeness or disk space."
    )
    d.row("Selected failure signals · selected time range")
    for i, (title, description, query) in enumerate(
        (
            (
                "Collector errors",
                "Observed collector/ingress exception records; retries can create several records for one outage.",
                count(collection_failures, source),
            ),
            (
                "Rejected writes",
                "Batch retries exhausted, invalid records or unwritten shutdown records. A log record is not a count of lost readings.",
                count(failed_writes, writer),
            ),
            (
                "Broker errors",
                "Error-level messages from EMQX or the source broker route. Worker collection excludes manager-hosted services.",
                count(level(broker, ERRORS), broker),
            ),
            (
                "Database errors",
                "PostgreSQL and db-sync error records; this does not poll database availability.",
                count(level(database, ERRORS), database),
            ),
        )
    ):
        d.metric(title, description, query, x=i * 6, w=6, kind="stat", alert=True)
    d.y += 4
    d.row("Source and MQTT transport")
    d.metric(
        "Collection interruptions by service",
        "Observed interruption records per bucket.",
        series(collection_failures),
    )
    d.metric(
        "MQTT / route warnings and errors",
        "Transport diagnostics by service. Unexpected disconnects are relevant even when no readings were selected.",
        series(level(broker)),
        x=12,
    )
    d.y += 8
    d.logs(
        "Collection interruption context",
        "Includes original exception and correlation context. Cross-check the application's Collection view for selected readings and readiness.",
        collection_failures,
    )
    d.y += 9
    d.row("Persistence · expand for retry and storage diagnostics")
    row_id = d.panels[-1]["id"]
    d.metric(
        "Writer retry and failure signals",
        "Retry attempts, database errors and exhausted batches can describe the same batch; do not sum this as lost batches.",
        series(fields(retries, "event"), "event"),
        legend="{{event}}",
    )
    slow = fields(events(writer, "db_writer[.]batch_slow"), "write_latency_s")
    d.metric(
        "Reported slow-write latency · maximum",
        "Maximum of emitted slow-write warnings per bucket, in seconds. Normal writes are absent; this is not overall database latency.",
        f'max_over_time({slow} | unwrap write_latency_s | __error__="" [$__interval]) by (service)',
        x=12,
        unit="s",
    )
    d.y += 8
    d.logs(
        "Writer failures and retries",
        "Original log records, including batch context. A retry warning alone does not prove data loss.",
        retries,
    )
    d.y += 9
    d.logs(
        "Database and schema warnings / errors",
        "For retention or initialization context, open Log investigation and select postgres or db-sync with Level = All.",
        level(database),
    )
    d.collapse_since(row_id)
    return d.document
