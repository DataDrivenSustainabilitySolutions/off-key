"""Live detector lifecycle and offline replay are related but distinct signals."""

from .common import (
    DETECTORS,
    RADAR,
    RADAR_FAILURES,
    Dashboard,
    count,
    events,
    fields,
    literal_filter,
    series,
    services,
    textbox,
)


def build():
    scope = literal_filter("reference")
    radar = RADAR + scope
    detectors = DETECTORS + scope
    dojo = services("dojo-worker") + scope
    failures = events(radar, RADAR_FAILURES)
    gaps = events(detectors, "radar[.]coverage_gap")
    d = Dashboard(
        "radar",
        "RADAR lifecycle, coverage and healthy runtime samples, followed by Dojo replay outcomes.",
        [
            textbox(
                "reference",
                "Run / monitor reference",
                "Case-insensitive literal substring in the original record. Applies to every panel, including Dojo.",
            ),
        ],
    )
    d.note(
        "**Lifecycle events describe transitions, not current state.** Use the application's Monitoring view "
        "for desired runs, readiness, anomaly evidence and input ownership. The reference filter accepts a run or monitor ID.\n\n"
        "Health summaries are emitted about once per minute **only while healthy**. Their absence can mean no monitors, "
        "degradation or missing logs. Dojo is offline replay; its outcomes are grouped separately below."
    )
    d.row("Live detection · observed events in the selected range")
    for i, (title, description, source) in enumerate(
        (
            (
                "Runtime starts",
                "Runtime-start records, including restored runs. Not the number of currently running monitors.",
                events(detectors, "radar[.]runtime_started"),
            ),
            (
                "To operational",
                "Transitions into operational state; a monitor can enter this state more than once.",
                fields(events(detectors, "radar[.]stage_changed"), "to")
                + ' | to="operational"',
            ),
            (
                "Failure signals",
                "Crash, startup, processing, ownership and persistence signals; multiple records may describe one incident.",
                failures,
            ),
            (
                "Coverage reports",
                "Throttled coverage reports. Each may summarize several dropped messages or possible gaps; not a count of lost readings.",
                gaps,
            ),
        )
    ):
        d.metric(
            title,
            description,
            count(source, radar),
            x=i * 6,
            w=6,
            kind="stat",
            alert=i >= 2,
        )
    d.y += 4
    d.metric(
        "Transitions by destination stage",
        "Transitions per bucket. A stage with no new transitions is not necessarily inactive.",
        series(fields(events(detectors, "radar[.]stage_changed"), "to"), "to"),
        legend="{{to}}",
    )
    d.metric(
        "Failure signals by event",
        "Separate operational symptoms before looking at the original exception.",
        series(fields(failures, "event"), "event"),
        x=12,
        legend="{{event}}",
    )
    d.y += 8
    d.logs(
        "RADAR failures and coverage gaps",
        "Original records retain monitor/run IDs and exceptions. Use Log investigation to follow all messages for a reference.",
        events(radar, RADAR_FAILURES + "|radar[.]coverage_gap"),
    )
    d.y += 9
    d.row("Runtime samples · expand for healthy detector measurements")
    row_id = d.panels[-1]["id"]
    summary = (
        events(detectors, "radar[.]health_summary")
        + ' | json monitor="extra.service_id" | __error__="" | monitor!=""'
    )
    for x, title, field, unit, description in (
        (
            0,
            "Reported processing throughput",
            "throughput",
            "ops",
            "Last healthy summary in a rolling 2m window, per monitor. Processing rate is measured by the runtime; absent/degraded monitors remain gaps. Shows up to ten highest values at each step.",
        ),
        (
            12,
            "Detector process memory",
            "memory_mb",
            "mbytes",
            "Last healthy process RSS sample in MiB over 2m, per monitor. This is process memory, not worker or container memory utilization. Shows up to ten highest values at each step.",
        ),
    ):
        query = f'topk(10, last_over_time({fields(summary, field)} | unwrap {field} | __error__="" [2m]) by (monitor))'
        d.metric(title, description, query, x=x, unit=unit, legend="{{monitor}}")
    d.y += 8
    d.logs(
        "Lifecycle, warm-up and calibration",
        "Transitions and startup/calibration completion records; use the app for the current stage and progress.",
        events(
            detectors,
            "radar[.](runtime_started|stage_changed|adaptive_warmup_complete|adaptive_calibration_complete|service_bootstrap_start|service_bootstrap_stopped)",
        ),
    )
    d.collapse_since(row_id)
    d.row("Dojo · expand for offline replay outcomes")
    row_id = d.panels[-1]["id"]
    for i, (title, pattern, description) in enumerate(
        (
            (
                "Replay completions",
                "dojo[.]run_finished",
                "Completion records for replay attempts; not a count of saved datasets.",
            ),
            (
                "Replay failures",
                "dojo[.]run_(failed|crashed)",
                "Includes domain failures logged at INFO and unexpected crashes. Retries may produce several outcomes for one run.",
            ),
            (
                "Replay requeues",
                "dojo[.]run_requeued",
                "Observed requeue records. This does not measure queue depth or queue wait time.",
            ),
        )
    ):
        d.metric(
            title,
            description,
            count(events(dojo, pattern), dojo),
            x=i * 8,
            w=8,
            kind="stat",
            alert=i == 1,
        )
    d.y += 4
    outcomes = events(
        dojo, "dojo[.]run_(started|finished|failed|crashed|requeued|stopped_elsewhere)"
    )
    d.metric(
        "Replay lifecycle by outcome",
        "Dojo events per bucket. Start, requeue and terminal records are not independent jobs.",
        series(fields(outcomes, "event"), "event"),
        w=24,
        legend="{{event}}",
    )
    d.y += 8
    d.logs(
        "Replay event context",
        "Expand a record for its run ID and outcome; the reference filter applies here too.",
        outcomes,
    )
    d.collapse_since(row_id)
    return d.document
