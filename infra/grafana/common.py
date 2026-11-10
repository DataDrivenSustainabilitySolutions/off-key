"""Small shared vocabulary for consistent dashboards and bounded LogQL queries."""

LOKI = {"type": "loki", "uid": "loki"}
ERRORS = "error|critical|fatal|panic"
WARNINGS = "warn|warning|" + ERRORS
CATALOGUE = (
    ("overview", "aberration-system-overview", "01 · Operations overview"),
    ("collection", "aberration-collection", "02 · Collection & persistence"),
    ("radar", "aberration-radar", "03 · RADAR & Dojo"),
    ("access", "aberration-access", "04 · HTTP & access"),
    ("logs", "aberration-logs", "05 · Log investigation"),
)


def selector(services=None):
    service = services or ".+"
    return f"{{stack=~`${{stack:regex}}`,node=~`${{node:regex}}`,service=~`{service}`}}"


def services(names):
    return selector("${stack:regex}_(" + names + ")")


APP = selector()[:-1] + ",service!~`${stack:regex}_log-canary`}"
CANARY = services("log-canary") + ' |= "observability_canary"'
RADAR = selector("radar|radar-preflight|${stack:regex}_(mqtt-radar|tactic)")
DETECTORS = selector("radar|${stack:regex}_mqtt-radar")
RADAR_FAILURES = (
    "tactic[.]radar_(task_crashed|worker_abandoned)|"
    "radar[.](service_start_failed|start_failed|fatal_error|execution_state_uncertain|"
    "health_degraded|message_processing_failed|model_error|db_batch_write_failed|"
    "db_retry_exhausted|db_checkpoint_ownership_lost|run_events_write_failed|"
    "checkpoint_loop_failed|final_checkpoint_failed)"
)


def level(source, levels=WARNINGS):
    return source + f' | detected_level=~"{levels}"'


def events(source, pattern):
    # Parse only needed fields. In production, key=value pairs are INSIDE the
    # JSON message, not top-level fields. Keep the original line for log panels.
    return (
        source
        + ' |= "event=" | json msg="message" | __error__=""'
        + f" | msg=~`(?s)^event=({pattern})( .*|$)`"
    )


def fields(source, *names):
    return (
        source
        + " | line_format `{{.msg}}` | logfmt "
        + ", ".join(names)
        + ' | __error__="" | drop msg'
    )


def literal_filter(variable):
    # Percent-encode before interpolation: quotes, backticks, regex operators
    # and newlines in an incident reference cannot change LogQL syntax.
    value = "${" + variable + ":percentencode}"
    return (
        # Optional decoding makes quoted/unicode text searchable as displayed.
        # Non-JSON infrastructure lines still participate via the raw fallback.
        ' | json search_message="message" | drop __error__, __error_details__'
        ' | label_format line_matches=`{{ if or (eq "' + value + '" "") '
        '(contains (lower (urldecode "' + value + '")) (lower (__line__))) '
        '(contains (lower (urldecode "'
        + value
        + '")) (lower .search_message)) }}yes{{ end }}`'
        ' | line_matches="yes" | drop line_matches, search_message'
    )


def count(source, baseline=None):
    query = f"sum(count_over_time({source} | drop msg [$__range]))"
    if baseline:
        # Zero means no matching records in an observed source, never healthy.
        query += f" or (0 * sum(count_over_time({baseline} [$__range])))"
    return query


def series(source, group="service", window="$__interval"):
    return f"sum by ({group}) (count_over_time({source} | drop msg [{window}]))"


def target(expr, legend="", instant=False, logs=False):
    result = {
        "refId": "A",
        "datasource": LOKI,
        "editorMode": "code",
        "expr": expr,
        "queryType": "instant" if instant else "range",
        "legendFormat": legend,
    }
    if logs:
        result.update(maxLines=200, direction="backward")
    return result


def variable(name, label, stream="", multi=True):
    return {
        "name": name,
        "label": label,
        "type": "query",
        "datasource": LOKI,
        "query": {"refId": name, "type": 1, "label": name, "stream": stream},
        "definition": f"label_values({stream + ', ' if stream else ''}{name})",
        "refresh": 2,
        "sort": 1,
        "multi": multi,
        "includeAll": multi,
        "allValue": ".+" if multi else None,
        "current": {"text": "All", "value": "$__all"} if multi else {},
        "options": [],
    }


def textbox(name, label, description):
    return {
        "name": name,
        "label": label,
        "type": "textbox",
        "query": "",
        "current": {"text": "", "value": ""},
        "description": description,
        "options": [],
    }


class Dashboard:
    def __init__(self, key, description, variables=()):
        _, uid, title = next(item for item in CATALOGUE if item[0] == key)
        self.panels = []
        self.y = 0
        self.next_id = 1
        self.document = {
            "id": None,
            "uid": uid,
            "title": title,
            "description": description,
            "tags": ["aberration", "operations", "provisioned"],
            "timezone": "browser",
            "schemaVersion": 39,
            "version": 1,
            "editable": False,
            "graphTooltip": 1,
            "refresh": "",
            "time": {"from": "now-1h", "to": "now"},
            "timepicker": {
                "refresh_intervals": ["1m", "5m", "15m"],
                "time_options": ["5m", "15m", "1h", "6h", "24h", "2d", "7d"],
            },
            "templating": {
                "list": [
                    variable("stack", "Stack", multi=False),
                    variable("node", "Worker", "{stack=~`${stack:regex}`}"),
                    *variables,
                ]
            },
            "links": [
                {
                    "type": "link",
                    "title": name,
                    "url": f"/d/{other_uid}",
                    "includeVars": True,
                    "keepTime": True,
                    "targetBlank": False,
                }
                for _, other_uid, name in CATALOGUE
                if other_uid != uid
            ],
            "annotations": {"list": []},
            "panels": self.panels,
        }

    def row(self, title):
        self.add("row", title, "", 0, 24, 1, collapsed=False, panels=[])
        self.y += 1

    def add(self, kind, title, description, x, w, h, **properties):
        panel = {
            "id": self.next_id,
            "type": kind,
            "title": title,
            "description": description,
            "gridPos": {"x": x, "y": self.y, "w": w, "h": h},
            **properties,
        }
        self.next_id += 1
        self.panels.append(panel)
        return panel

    def note(self, text):
        self.add(
            "text",
            "Reading this dashboard",
            "",
            0,
            24,
            5,
            options={"mode": "markdown", "content": text},
            transparent=True,
        )
        self.y += 5

    def metric(
        self,
        title,
        description,
        expr,
        x=0,
        w=12,
        kind="timeseries",
        unit="short",
        legend="{{service}}",
        alert=False,
    ):
        stat = kind == "stat"
        defaults = {
            "unit": unit,
            "min": 0,
            "noValue": "No observations",
            "color": {"mode": "thresholds" if stat else "palette-classic"},
            "thresholds": {
                "mode": "absolute",
                "steps": [
                    {"color": "blue", "value": None},
                    *([{"color": "red", "value": 1}] if alert else []),
                ],
            },
        }
        if stat:
            defaults["decimals"] = 0
            options = {
                "reduceOptions": {
                    "calcs": ["lastNotNull"],
                    "fields": "",
                    "values": False,
                },
                "colorMode": "value",
                "graphMode": "none",
                "textMode": "auto",
                "orientation": "auto",
            }
        else:
            defaults["custom"] = {
                "drawStyle": "line",
                "lineInterpolation": "stepAfter",
                "lineWidth": 1,
                "fillOpacity": 10,
                "showPoints": "never",
                "spanNulls": False,
                "axisCenteredZero": False,
                "stacking": {"mode": "none", "group": "A"},
            }
            options = {
                "legend": {"displayMode": "table", "placement": "bottom", "calcs": []},
                "tooltip": {"mode": "multi", "sort": "desc"},
            }
        return self.add(
            kind,
            title,
            description,
            x,
            w,
            4 if stat else 8,
            datasource=LOKI,
            targets=[target(expr, legend, instant=stat)],
            interval="1m",
            maxDataPoints=180,
            fieldConfig={"defaults": defaults, "overrides": []},
            options=options,
        )

    def logs(self, title, description, expr, x=0, w=24):
        self.add(
            "logs",
            title,
            description,
            x,
            w,
            9,
            datasource=LOKI,
            targets=[target(expr, logs=True)],
            options={
                "showTime": True,
                "showLabels": False,
                "showCommonLabels": False,
                "wrapLogMessage": True,
                "prettifyLogMessage": True,
                "enableLogDetails": True,
                "dedupStrategy": "none",
                "sortOrder": "Descending",
            },
        )

    def collapse_since(self, row_id):
        """Defer the more expensive diagnostic queries until the row is opened."""
        index = next(i for i, panel in enumerate(self.panels) if panel["id"] == row_id)
        row = self.panels[index]
        row["collapsed"] = True
        row["panels"] = self.panels[index + 1 :]
        del self.panels[index + 1 :]
        self.y = row["gridPos"]["y"] + 1
