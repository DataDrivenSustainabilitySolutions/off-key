"""One consistent scope for counts and raw records, with safe literal search."""

from .common import (
    Dashboard,
    count,
    literal_filter,
    selector,
    series,
    textbox,
    variable,
)


def build():
    severity = {
        "name": "severity",
        "label": "Level",
        "type": "custom",
        "query": "All : .*, Warnings and errors : warn|warning|error|critical|fatal|panic, Errors : error|critical|fatal|panic, Warnings : warn|warning, Info : info, Debug / trace : debug|trace, Unclassified : unknown|^$",
        "current": {"text": "All", "value": ".*"},
        "options": [],
        "multi": False,
        "includeAll": False,
    }
    d = Dashboard(
        "logs",
        "Scope, correlate and inspect original records from all collected worker services.",
        [
            variable(
                "service", "Service", "{stack=~`${stack:regex}`,node=~`${node:regex}`}"
            ),
            severity,
            textbox(
                "search",
                "Contains",
                "Case-insensitive literal substring, applied to every panel. Paste a correlation ID, run ID, monitor ID or message fragment.",
            ),
        ],
    )
    source = (
        selector("${service:regex}")
        + " | detected_level=~${severity:doublequote}"
        + literal_filter("search")
    )
    d.note(
        "**Choose the worker and service, then paste an incident reference.** All panels use the same "
        "Service, Worker, Level and literal Contains filters. Expand a record to inspect its original fields.\n\n"
        "Newest **200 lines** are shown per log panel; narrow the time range or continue in Explore for more. "
        "Level is Loki's detected severity (unclassified records remain available). Manager-only services and "
        "collector self-logs are outside this worker log collection. Auto-refresh is off while investigating."
    )
    d.row("Matching records · selected scope")
    d.metric(
        "Matching lines observed",
        "Count across the selected range, not just the newest 200 displayed below. Empty means no matching records; it does not prove a healthy service.",
        count(source),
        kind="stat",
        w=8,
    )
    d.metric(
        "Services with matching lines",
        "Observed services in this filtered range, not desired service replicas.",
        f"count({series(source, 'service', '$__range')})",
        x=8,
        w=8,
        kind="stat",
    )
    d.metric(
        "Workers with matching lines",
        "Observed senders in this filtered range, not node health.",
        f"count({series(source, 'node', '$__range')})",
        x=16,
        w=8,
        kind="stat",
    )
    d.y += 4
    d.metric(
        "Matching lines by level",
        "Count per bucket after every filter, including literal Contains. Unknown level does not mean INFO.",
        series(source, "detected_level"),
        legend="{{detected_level}}",
    )
    d.metric(
        "Matching lines by service",
        "The same scope as the raw records below; counts include matches beyond the display limit.",
        series(source),
        x=12,
    )
    d.y += 8
    d.row("Original records · newest first")
    d.logs(
        "Matching log lines",
        "No deduplication: repeated records remain visible. Correlation IDs and run UUIDs remain in the record, not indexed Loki stream labels.",
        source,
    )
    d.y += 9
    return d.document
