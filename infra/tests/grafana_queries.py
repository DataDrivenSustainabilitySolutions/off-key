"""Exercise the shipped queries against Loki, including real-shaped log records.

Only the disposable observability rehearsal calls the fixture writer. Production
checks may use panel_queries() and read-only format/query endpoints separately.
"""

import json
import re
import time
import urllib.parse
from pathlib import Path


def panels(document):
    for panel in document.get("panels", []):
        yield panel
        yield from panels(panel)


def interpolate(expression, stack, *, search="", reference="", node=".+", window="5m"):
    values = {
        "${stack:regex}": re.escape(stack),
        "${node:regex}": node,
        "${service:regex}": ".+",
        "${severity:doublequote}": '".*"',
        "${search:percentencode}": urllib.parse.quote(search, safe=""),
        "${reference:percentencode}": urllib.parse.quote(reference, safe=""),
        "$__range": window,
        "$__interval": "1m",
    }
    for variable, value in values.items():
        expression = expression.replace(variable, value)
    if re.search(r"\$\{|\$__", expression):
        raise ValueError("Unresolved Grafana variable")
    return expression


def panel_queries(directory, stack, **variables):
    for path in sorted(Path(directory).glob("grafana-dashboard-*.json")):
        document = json.loads(path.read_text())
        for panel in panels(document):
            for target in panel.get("targets", []):
                yield {
                    "dashboard": document["uid"],
                    "panel": panel["title"],
                    "type": panel["type"],
                    "query_type": target["queryType"],
                    "expr": interpolate(target["expr"], stack, **variables),
                }


def verify_provisioned(directory, request):
    """Read the anonymous, isolated lab Grafana; never impersonate a live user."""
    count = 0
    for path in sorted(Path(directory).glob("grafana-dashboard-*.json")):
        expected = json.loads(path.read_text())
        result = request("/api/dashboards/uid/" + expected["uid"])
        assert result["meta"]["provisioned"], expected["uid"]
        assert result["dashboard"]["title"] == expected["title"]
        assert len(list(panels(result["dashboard"]))) == len(list(panels(expected)))
        count += 1
    home = request("/api/dashboards/home")
    # Grafana 13 serves a configured home file through its synthetic home UID.
    assert (
        home.get("redirectUri", "").startswith("/d/default-home-dashboard/")
        or home.get("dashboard", {}).get("uid") == "aberration-system-overview"
    )
    return {"provisioned_dashboards": count, "provisioned_home_dashboard": True}


def verify_queries(directory, stack, request):
    """Validate syntax AND evaluation using a bounded, synthetic log fixture."""
    now = time.time_ns()
    scope = stack + "-dashboard-fixture"
    reference = 'literal `quote" \\ .*[x] % snowman ☃'
    records = [
        ("log-canary", "fresh", 10, {"event": "observability_canary"}),
        ("log-canary", "silent", 600, {"event": "observability_canary"}),
        (
            "api",
            "fresh",
            10,
            {
                "level": "ERROR",
                "message": "event=http.request_failed method=GET path=/fixture duration_ms=42.5",
            },
        ),
        (
            "api",
            "fresh",
            11,
            {
                "level": "WARNING",
                "message": "event=security.authentication_failed ip=redacted path=/fixture suppressed=3",
            },
        ),
        (
            "api",
            "fresh",
            12,
            {
                "level": "WARNING",
                "message": "event=security.suspicious_request method=GET path=/fixture suppressed=2",
            },
        ),
        (
            "api",
            "fresh",
            13,
            {"level": "ERROR", "message": "event=password_reset_delivery_failed"},
        ),
        ("api", "fresh", 14, {"level": "INFO", "message": reference}),
        (
            "api",
            "fresh",
            15,
            {
                "level": "INFO",
                "message": "quoted event=http.request_failed is not an event",
            },
        ),
        ("api", "fresh", 16, {"level": "INFO", "event": "http.request_failed"}),
        ("api", "fresh", 17, "not json: event=http.request_failed"),
        ("mqtt-proxy", "fresh", 10, {"level": "ERROR", "message": "Collection failed"}),
        (
            "mqtt-proxy",
            "fresh",
            11,
            {
                "level": "WARNING",
                "message": "event=db_writer.batch_retry batch_id=fixture batch_size=12",
            },
        ),
        (
            "mqtt-proxy",
            "fresh",
            12,
            {
                "level": "WARNING",
                "message": "event=db_writer.batch_slow batch_size=12 write_latency_s=1.5",
            },
        ),
        ("postgres", "fresh", 10, "ERROR: synthetic database error"),
        (
            "emqx-main",
            "fresh",
            10,
            {"level": "warning", "message": "synthetic disconnect"},
        ),
        (
            "tactic",
            "fresh",
            10,
            {"level": "ERROR", "message": "System ingress interrupted; retrying"},
        ),
        (
            "radar",
            "fresh",
            10,
            {
                "level": "INFO",
                "message": "event=radar.runtime_started stage=warming_up restored=False",
                "extra": {"service_id": "monitor-a"},
            },
        ),
        (
            "radar",
            "fresh",
            11,
            {
                "level": "INFO",
                "message": "event=radar.stage_changed from=calibrating to=operational previous_stage_seconds=3",
                "extra": {"service_id": "monitor-a"},
            },
        ),
        (
            "radar",
            "fresh",
            12,
            {
                "level": "WARNING",
                "message": "event=radar.coverage_gap new_losses=5 last_gap_reason=queue_full",
                "extra": {"service_id": "monitor-a"},
            },
        ),
        (
            "radar",
            "fresh",
            13,
            {
                "level": "ERROR",
                "message": "event=radar.health_degraded status=degraded alerts=fixture",
                "extra": {"service_id": "monitor-a"},
            },
        ),
        (
            "radar",
            "fresh",
            14,
            {
                "level": "INFO",
                "message": "event=radar.health_summary status=healthy throughput=12 memory_mb=128",
                "extra": {"service_id": "monitor-a"},
            },
        ),
        (
            "radar",
            "fresh",
            70,
            {
                "level": "INFO",
                "message": "event=radar.health_summary status=healthy throughput=20 memory_mb=256",
                "extra": {"service_id": "monitor-a"},
            },
        ),
        (
            "dojo-worker",
            "fresh",
            10,
            {
                "level": "INFO",
                "message": "event=dojo.run_finished run_id=replay-a points=30 results=30",
            },
        ),
        (
            "dojo-worker",
            "fresh",
            11,
            {
                "level": "INFO",
                "message": "event=dojo.run_failed run_id=replay-b error=fixture",
            },
        ),
        # Same service suffix in another stack must never bleed into this scope.
        (
            "foreign-api",
            "fresh",
            10,
            {
                "level": "ERROR",
                "message": "event=http.request_failed method=GET path=/foreign duration_ms=999",
            },
        ),
    ]
    streams = {}
    for service, node, age, record in records:
        tenant = scope + "-foreign" if service == "foreign-api" else scope
        name = (
            "radar"
            if service == "radar"
            else tenant + "_" + service.removeprefix("foreign-")
        )
        labels = {"stack": tenant, "node": node, "service": name}
        key = (tenant, node, name)
        stream = streams.setdefault(key, {"stream": labels, "values": []})
        line = json.dumps(record) if isinstance(record, dict) else record
        stream["values"].append([str(now - age * 10**9), line])
    for stream in streams.values():
        stream["values"].sort(key=lambda value: int(value[0]))
    request("/loki/api/v1/push", {"streams": list(streams.values())})

    def instant(query):
        response = request(
            "/loki/api/v1/query?"
            + urllib.parse.urlencode({"query": query, "time": str(now)})
        )
        assert response["status"] == "success"
        return response["data"]["result"]

    queries = list(panel_queries(directory, scope))
    for query in queries:
        response = request(
            "/loki/api/v1/format_query?"
            + urllib.parse.urlencode({"query": query["expr"]})
        )
        assert response["status"] == "success", query["panel"]
        if query["type"] == "logs":
            response = request(
                "/loki/api/v1/query_range?"
                + urllib.parse.urlencode(
                    {
                        "query": query["expr"],
                        "start": str(now - 300 * 10**9),
                        "end": str(now),
                        "limit": 30,
                    }
                )
            )
            assert response["status"] == "success", query["panel"]
        else:
            instant(query["expr"])

    by_title = {query["panel"]: query["expr"] for query in queries}
    for title, expected in {
        "Fresh workers": 1,
        "Silent workers": 1,
        "HTTP exceptions": 1,
        "Access warnings": 1,
        "Email failures": 1,
        "Collector errors": 2,
        "Rejected writes": 0,
        "Runtime starts": 1,
        "To operational": 1,
        "Coverage reports": 1,
        "Replay failures": 1,
        "Replay completions": 1,
        "Replay requeues": 0,
        "Reported processing throughput": 12,
        "Detector process memory": 128,
    }.items():
        rows = instant(by_title[title])
        assert len(rows) == 1 and float(rows[0]["value"][1]) == expected, title
    absent = by_title["HTTP exceptions"].replace(re.escape(scope), "absent-fixture")
    assert instant(absent) == [], "Missing telemetry must not become zero"
    for query in panel_queries(directory, scope, search=reference):
        if query["panel"] == "Matching lines observed":
            assert float(instant(query["expr"])[0]["value"][1]) == 1
    return {
        "dashboard_queries_evaluated": len(queries),
        "dashboard_signal_semantics": True,
    }
