"""Start with delivery confidence, then failures, then a focused investigation."""

from .common import (
    APP,
    CANARY,
    ERRORS,
    RADAR,
    RADAR_FAILURES,
    Dashboard,
    count,
    events,
    level,
    series,
)


def build():
    d = Dashboard(
        "overview",
        "Operational triage for the MQTT → collection → database → RADAR pipeline.",
    )
    d.document["refresh"] = "1m"
    d.note(
        "**Start with log delivery, then investigate the affected service.** "
        "MQTT sources → TACTIC ingress → MQTT proxy → TimescaleDB / accepted MQTT → RADAR. "
        "Dojo replays stored datasets. Use the dashboard links above for detail.\n\n"
        "These are **log observations**, not uptime, desired replica counts, queue depth, or an SLO. "
        "A quiet service may be healthy or unavailable. No observations stays empty; zero only means "
        "no matching events in a source that emitted logs. Retention: seven days."
    )
    d.row("Log delivery · check this before trusting silence")
    fresh = f"sum by (node) (count_over_time({CANARY} [2m]))"
    seen = f"sum by (node) (count_over_time({CANARY} [24h]))"
    d.metric(
        "Fresh workers",
        "Observed canary senders at the selected end time; compare with active Swarm workers. This is not an expected-worker inventory.",
        f"count({fresh}) or (0 * count({seen}))",
        kind="stat",
        w=6,
    )
    d.metric(
        "Silent workers",
        "Workers seen in the preceding 24h with no canary in 2m. Includes deliberately drained/removed nodes; cannot detect a worker never seen by Loki.",
        f"count(({seen}) unless ({fresh})) or (0 * count({seen}))",
        x=6,
        w=6,
        kind="stat",
        alert=True,
    )
    d.metric(
        "Error records",
        "Error/critical/fatal/panic lines during the selected range. Zero is an observed log count, not proof of service health.",
        count(level(APP, ERRORS), APP),
        x=12,
        w=6,
        kind="stat",
        alert=True,
    )
    d.metric(
        "RADAR failures",
        "Startup, crash, degradation, processing and persistence events. Multiple signals can describe the same failure; this is not a failed-run count.",
        count(events(RADAR, RADAR_FAILURES), RADAR),
        x=18,
        w=6,
        kind="stat",
        alert=True,
    )
    d.y += 4
    d.metric(
        "Canary arrivals by worker · rolling 5m",
        "Each active worker emits every 30s (roughly ten records per window). Gaps remain visible. Collector and manager logs are intentionally excluded.",
        series(CANARY, "node", "5m"),
        legend="{{node}}",
    )
    d.metric(
        "Warnings and errors by service",
        "Observed lines per bucket, at least one minute wide. Compare services before opening their focused dashboard.",
        series(level(APP)),
        x=12,
    )
    d.y += 8
    d.row("Application signals · follow the evidence")
    d.logs(
        "Recent application errors",
        "Expand a record for its correlation ID, monitor ID or exception. Copy an ID into Log investigation. Newest 200 matching lines.",
        level(APP, ERRORS),
    )
    d.y += 9
    d.row("Logging volume · expand when investigating noisy sources")
    row_id = d.panels[-1]["id"]
    d.metric(
        "Log lines per second",
        "Log traffic only, not application throughput. Loki's ingestion budget is shared by the stack.",
        f"sum by (service) (rate({APP} [$__interval]))",
        unit="ops",
    )
    d.metric(
        "Log payload bytes per second",
        "Uncompressed log-line bytes as observed by Loki. This excludes protocol overhead and does not measure filesystem use.",
        f"sum by (service) (bytes_rate({APP} [$__interval]))",
        x=12,
        unit="Bps",
    )
    d.collapse_since(row_id)
    return d.document
