"""Only signals available with production request logging intentionally disabled."""

from .common import ERRORS, Dashboard, count, events, fields, level, series, services


def build():
    api = services("api")
    backend = services("api|tactic")
    failures = events(api, "http[.]request_failed")
    denied = events(api, "security[.](authentication_failed|authorization_failed)")
    suspicious = events(api, "security[.]suspicious_request")
    delivery = events(
        api,
        "member_invitation_delivery_failed|password_reset_delivery_failed|gateway[.]alarm_email_failed",
    )
    security = events(
        api,
        "security[.](authentication_failed|authorization_failed|suspicious_request)",
    )
    d = Dashboard(
        "access",
        "Recorded HTTP exceptions, access-control signals and notification failures.",
    )
    d.note(
        "**Production disables successful-request and performance logging.** These panels show recorded "
        "exceptions and access events; they cannot provide request throughput, total 4xx/5xx counts, "
        "availability or overall latency.\n\n"
        "Access warnings are **throttled per event/client over 60s**. A later warning reports suppressed "
        "occurrences; a quiet tail may never report them. Suspicious-pattern matches are diagnostic hints, "
        "not confirmed attacks. IDs and paths remain in records, not chart series."
    )
    d.row("Recorded symptoms · selected time range")
    for i, (title, description, source) in enumerate(
        (
            (
                "HTTP exceptions",
                "http.request_failed records only; handled HTTP errors and successful requests are not included.",
                failures,
            ),
            (
                "Access warnings",
                "Throttled warning records, not total denied requests or unique clients.",
                denied,
            ),
            (
                "Path warnings",
                "Throttled path-pattern matches. Legitimate requests can match these heuristics.",
                suspicious,
            ),
            (
                "Email failures",
                "Invitation, password-reset and alarm email failure records. Not a full SMTP delivery metric.",
                delivery,
            ),
        )
    ):
        d.metric(
            title,
            description,
            count(source, api),
            x=i * 6,
            w=6,
            kind="stat",
            alert=i in (0, 3),
        )
    d.y += 4
    d.metric(
        "API / TACTIC error records",
        "Observed error-level lines by service. TACTIC errors are not necessarily visible HTTP failures.",
        series(level(backend, ERRORS)),
    )
    d.metric(
        "Access warnings by event",
        "Emitted warning records per bucket; suppression means this undercounts actual occurrences.",
        series(fields(security, "event"), "event"),
        x=12,
        legend="{{event}}",
    )
    d.y += 8
    d.logs(
        "HTTP and backend error context",
        "Original exceptions preserve correlation IDs. Copy a reference into Log investigation to follow Gateway → TACTIC.",
        level(backend, ERRORS),
    )
    d.y += 9
    d.row("Access and notifications · expand for diagnostic context")
    row_id = d.panels[-1]["id"]
    suppressed = fields(security, "event", "suppressed")
    d.metric(
        "Suppressed occurrences subsequently reported",
        "Sum of suppressed values in newly emitted warnings. Values refer to prior suppression windows; pending unreported occurrences are absent.",
        f'sum by (event) (sum_over_time({suppressed} | unwrap suppressed | __error__="" [$__interval]))',
        w=24,
        legend="{{event}}",
    )
    d.y += 8
    d.logs(
        "Access-warning context",
        "Use the redacted request context for investigation. These are heuristic/throttled diagnostics, not an audit trail.",
        security,
    )
    d.y += 9
    d.logs(
        "Notification-delivery context",
        "Application notification failures are separate from Grafana alert delivery. No alert notification receiver is configured by these dashboards.",
        delivery,
    )
    d.collapse_since(row_id)
    return d.document
