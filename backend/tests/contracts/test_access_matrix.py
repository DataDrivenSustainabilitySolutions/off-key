"""Who may call each route of the API, in one readable table.

A route may require the signed-in member or one permission; on "monitors" and
"alarms" every member reads and changes need manage_monitors or manage_alarms.
The background worker serves no route but its probes. A new route fails these
tests until it is added to its table, so a change to access is always a
deliberate, reviewed edit.

An agent's key is a second kind of caller. It has no permissions: a route is
closed to keys until it is listed in the tables of what a key reaches, "any"
for every key and "start" for a key that may start monitoring services.
"""

from collections import defaultdict

import pytest
from fastapi.routing import iter_route_contexts
from off_key_api_gateway.api import access
from off_key_api_gateway.app import build_app
from off_key_api_gateway.settings import AppSettings
from off_key_core.auth.agents import AGENT_ACCESS
from off_key_core.auth.permissions import Permission
from off_key_tactic_middleware.main import create_app

GATEWAY_ACCESS = {
    "public": {
        "GET /v1/demo",
        "GET /docs",
        "GET /docs/oauth2-redirect",
        "GET /health",
        "GET /redoc",
        "POST /v1/auth/accept-invitation",
        "POST /v1/auth/password-reset",
        "POST /v1/auth/password-reset/confirm",
        "POST /v1/auth/login",
        "POST /v1/auth/logout",
        "POST /v1/auth/refresh",
    },
    "member": {
        "GET /v1/agents/me",
        "POST /v1/alarms/query",
        "GET /v1/detectors",
        "GET /v1/evidence",
        "GET /v1/evidence/chart",
        "GET /v1/pipeline-components",
        "GET /v1/pipeline-components/search",
        "GET /v1/pipeline-components/{component_id}",
        "GET /v1/devices",
        "GET /v1/devices/{device_id}/readings",
        "DELETE /v1/favorites",
        "GET /v1/favorites",
        "POST /v1/favorites",
        "GET /v1/me",
        "GET /v1/permissions",
        "GET /v1/roles",
        "GET /v1/catalogue",
        "GET /v1/catalogue/revisions",
        "GET /v1/live/measurements",
        "GET /v1/recording/health",
        "POST /v1/recording/status",
        "GET /v1/storage",
        "GET /v1/readings/{reading_id}/measurements",
        "GET /v1/readings/{reading_id}/measurements/buckets",
        "GET /v1/readings/{reading_id}/profile",
    },
    "monitors": {
        "GET /v1/forecast-models",
        "POST /v1/forecast-models/downloads",
        "GET /v1/monitors",
        "POST /v1/monitors",
        "GET /v1/monitors/overview",
        "DELETE /v1/monitors/{monitor_id}",
        "GET /v1/monitors/{monitor_id}",
        "PATCH /v1/monitors/{monitor_id}",
        "GET /v1/monitors/{monitor_id}/pipeline",
        "GET /v1/monitors/{monitor_id}/pipeline/history",
        "PUT /v1/monitors/{monitor_id}/pipeline/layout",
        "GET /v1/monitors/{monitor_id}/pipeline/metadata",
        "GET /v1/monitors/{monitor_id}/pipeline/state",
        "GET /v1/monitors/{monitor_id}/pipeline/timeline",
        "POST /v1/monitors/{monitor_id}/stop",
        "POST /v1/pipeline-activations",
        "GET /v1/pipeline-activations/{activation_id}",
        "POST /v1/pipeline-activations/{activation_id}/cancel",
        "GET /v1/pipeline-blocks",
        "POST /v1/pipeline-blocks",
        "DELETE /v1/pipeline-blocks/{block_id}",
        "GET /v1/pipeline-proposals",
        "POST /v1/pipeline-proposals",
        "GET /v1/pipeline-proposals/{proposal_id}",
        "POST /v1/pipeline-proposals/{proposal_id}/decision",
        "POST /v1/pipeline-proposals/{proposal_id}/withdraw",
        "GET /v1/pipelines",
        "POST /v1/pipelines",
        "POST /v1/pipelines/apply",
        "POST /v1/pipelines/edit",
        "POST /v1/pipelines/validate",
        "GET /v1/pipelines/{pipeline_id}",
        "PATCH /v1/pipelines/{pipeline_id}",
        "PUT /v1/pipelines/{pipeline_id}/draft",
        "GET /v1/pipelines/{pipeline_id}/revisions",
        "POST /v1/pipelines/{pipeline_id}/revisions",
        "GET /v1/pipelines/{pipeline_id}/revisions/{revision_id}",
        "GET /v1/pipelines/{pipeline_id}/revisions/{revision_id}/metadata",
        "POST /v1/pipelines/{pipeline_id}/validate",
    },
    "manage_monitors": {
        # Also behind the Dojo router's use_dojo; see test_dojo_promotion.
        "POST /v1/dojo/runs/{run_id}/promote",
    },
    "alarms": {
        "GET /v1/alarms",
        "POST /v1/alarms",
        "GET /v1/alarms/count",
        "DELETE /v1/alarms/{alarm_id}",
        "GET /v1/alarms/{alarm_id}",
        "POST /v1/alarms/deletion-preview",
        "POST /v1/alarms/delete",
    },
    "manage_sources": {
        "DELETE /v1/live/views/{view_id}",
        "POST /v1/brokers/check",
        "POST /v1/brokers/{broker_id}/reconnect",
        "POST /v1/live/views",
        "POST /v1/live/views/{view_id}/renew",
        "POST /v1/recording/preview",
        "PUT /v1/catalogue",
        "PUT /v1/recording",
    },
    "use_dojo": {
        "GET /v1/dojo/datasets",
        "POST /v1/dojo/datasets/csv",
        "POST /v1/dojo/datasets/history",
        "DELETE /v1/dojo/datasets/{dataset_id}",
        "GET /v1/dojo/datasets/{dataset_id}",
        "PATCH /v1/dojo/datasets/{dataset_id}",
        "GET /v1/dojo/datasets/{dataset_id}/series/{series_id}/points",
        "GET /v1/dojo/datasets/{dataset_id}/comparison",
        "GET /v1/dojo/datasets/{dataset_id}/labels",
        "GET /v1/dojo/datasets/{dataset_id}/label-suggestions",
        "POST /v1/dojo/datasets/{dataset_id}/labels",
        "POST /v1/dojo/datasets/{dataset_id}/labels/batch",
        "DELETE /v1/dojo/datasets/{dataset_id}/labels/{label_id}",
        "PATCH /v1/dojo/datasets/{dataset_id}/labels/{label_id}",
        "GET /v1/dojo/runs",
        "POST /v1/dojo/runs",
        "DELETE /v1/dojo/runs/{run_id}",
        "GET /v1/dojo/runs/{run_id}",
        "POST /v1/dojo/runs/{run_id}/cancel",
        "GET /v1/dojo/runs/{run_id}/metrics",
        "GET /v1/dojo/runs/{run_id}/calibration",
        "GET /v1/dojo/runs/{run_id}/results",
        "GET /v1/dojo/runs/{run_id}/outline",
        "GET /v1/dojo/runs/{run_id}/steps",
    },
    "manage_members": {
        "GET /v1/agents",
        "POST /v1/agents",
        "DELETE /v1/agents/{agent_id}",
        "PATCH /v1/agents/{agent_id}",
        "POST /v1/invitations",
        "GET /v1/members",
        "DELETE /v1/members/{member_id}",
        "PATCH /v1/members/{member_id}",
        "POST /v1/roles",
        "DELETE /v1/roles/{role_id}",
        "PATCH /v1/roles/{role_id}",
    },
}


# What an agent's key reaches. Everything else answers a key with 403.
GATEWAY_AGENT_ACCESS = {
    "any": {
        "GET /v1/agents/me",
        "GET /v1/alarms",
        "GET /v1/alarms/count",
        "POST /v1/alarms/query",
        "GET /v1/detectors",
        "GET /v1/devices",
        "GET /v1/devices/{device_id}/readings",
        "GET /v1/dojo/datasets",
        "POST /v1/dojo/datasets/history",
        "GET /v1/dojo/datasets/{dataset_id}",
        "GET /v1/dojo/datasets/{dataset_id}/series/{series_id}/points",
        "GET /v1/dojo/datasets/{dataset_id}/comparison",
        "GET /v1/dojo/datasets/{dataset_id}/labels",
        "GET /v1/dojo/datasets/{dataset_id}/label-suggestions",
        "GET /v1/dojo/runs",
        "POST /v1/dojo/runs",
        "GET /v1/dojo/runs/{run_id}",
        "GET /v1/dojo/runs/{run_id}/metrics",
        "GET /v1/dojo/runs/{run_id}/calibration",
        "GET /v1/dojo/runs/{run_id}/results",
        "GET /v1/dojo/runs/{run_id}/outline",
        "GET /v1/dojo/runs/{run_id}/steps",
        "GET /v1/evidence",
        "GET /v1/evidence/chart",
        "GET /v1/forecast-models",
        "GET /v1/monitors",
        "GET /v1/monitors/overview",
        "GET /v1/monitors/{monitor_id}",
        "GET /v1/monitors/{monitor_id}/pipeline",
        "GET /v1/monitors/{monitor_id}/pipeline/history",
        "GET /v1/monitors/{monitor_id}/pipeline/metadata",
        "GET /v1/monitors/{monitor_id}/pipeline/state",
        "GET /v1/monitors/{monitor_id}/pipeline/timeline",
        "GET /v1/pipeline-activations/{activation_id}",
        "GET /v1/pipeline-blocks",
        "GET /v1/pipeline-proposals",
        "POST /v1/pipeline-proposals",
        "GET /v1/pipeline-proposals/{proposal_id}",
        "POST /v1/pipeline-proposals/{proposal_id}/withdraw",
        "GET /v1/pipeline-components",
        "GET /v1/pipeline-components/search",
        "GET /v1/pipeline-components/{component_id}",
        "GET /v1/pipelines",
        "POST /v1/pipelines/edit",
        "POST /v1/pipelines/validate",
        "GET /v1/pipelines/{pipeline_id}",
        "GET /v1/pipelines/{pipeline_id}/revisions",
        "GET /v1/pipelines/{pipeline_id}/revisions/{revision_id}",
        "GET /v1/pipelines/{pipeline_id}/revisions/{revision_id}/metadata",
        "GET /v1/readings/{reading_id}/measurements",
        "GET /v1/readings/{reading_id}/measurements/buckets",
        "GET /v1/readings/{reading_id}/profile",
    },
    "start": {
        "POST /v1/pipeline-activations/{activation_id}/cancel",
        "POST /v1/pipelines/apply",
    },
}


def _calls(dependant):
    yield dependant.call
    for dependency in dependant.dependencies:
        yield from _calls(dependency)


def _routes(app):
    """(method, path, dependency callables, what the route opens to a key),
    router-level dependencies included."""
    for context in iter_route_contexts(app.routes):
        # Since FastAPI 0.140 an included router's dependencies live on the
        # effective route context rather than on the original APIRoute.
        effective = getattr(context, "_route_context", None)
        dependant = getattr(effective, "dependant", None) or getattr(
            context.route, "dependant", None
        )
        if dependant is None:
            continue
        opened = (getattr(context.route, "openapi_extra", None) or {}).get(AGENT_ACCESS)
        for method in context.methods or ():
            if method != "HEAD":
                yield f"{method} {context.path}", set(_calls(dependant)), opened


def _classify(app, levels):
    found = defaultdict(set)
    for route, calls, _ in _routes(app):
        level = next((name for name, call in levels if call in calls), "public")
        found[level].add(route)
    return dict(found)


def _open_to_keys(app, auth):
    """The routes a key reaches, by what they ask of it.

    A route opens itself to keys and resolves the caller, and nothing it
    depends on asks for a member, which would refuse the key after all.
    """
    found = defaultdict(set)
    for route, calls, opened in _routes(app):
        if opened is None:
            continue
        assert auth.current_caller in calls, route
        assert auth.current_member not in calls, route
        found[opened].add(route)
    return dict(found)


def test_the_worker_serves_its_probes_and_nothing_else():
    """Every call from outside reaches the API; the worker only reports health."""
    found = {route for route, _, _ in _routes(create_app())}
    assert found == {"GET /health", "GET /ready"}


def test_gateway_routes_match_the_access_table():
    found = _classify(
        build_app(AppSettings(APP_NAME="off-key-test")),
        [
            *(
                (permission.value, access.require_permission(permission))
                for permission in Permission
            ),
            ("monitors", access.writes_require(Permission.manage_monitors)),
            ("alarms", access.writes_require(Permission.manage_alarms)),
            ("member", access.current_caller),
        ],
    )
    assert found == GATEWAY_ACCESS


def test_a_key_reaches_only_the_listed_gateway_routes():
    app = build_app(AppSettings(APP_NAME="off-key-test"))
    assert _open_to_keys(app, access) == GATEWAY_AGENT_ACCESS


def test_a_key_changes_nothing_it_did_not_make():
    """Beyond reads, a key validates, edits what it holds, tests, proposes,
    withdraws its own proposal and, where it may, starts."""
    writes = {
        route
        for routes in GATEWAY_AGENT_ACCESS.values()
        for route in routes
        if not route.startswith("GET ")
    }
    assert writes == {
        "POST /v1/alarms/query",
        "POST /v1/dojo/datasets/history",
        "POST /v1/dojo/runs",
        "POST /v1/pipelines/edit",
        "POST /v1/pipelines/validate",
        "POST /v1/pipelines/apply",
        "POST /v1/pipeline-activations/{activation_id}/cancel",
        "POST /v1/pipeline-proposals",
        "POST /v1/pipeline-proposals/{proposal_id}/withdraw",
    }


@pytest.mark.parametrize("route", sorted(GATEWAY_ACCESS["public"]))
def test_public_gateway_routes_are_documentation_health_sign_in_or_demo_status(route):
    path = route.split()[1]
    assert path in {
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/health",
        "/v1/demo",
    } or (path.startswith("/v1/auth/"))


def test_gateway_openapi_marks_exactly_the_protected_routes_with_bearer():
    """Agents and generated clients learn from the schema which calls need a token."""
    schema = build_app(AppSettings(APP_NAME="off-key-test")).openapi()
    scheme = schema["components"]["securitySchemes"]["bearerAuth"]
    assert (scheme["type"], scheme["scheme"]) == ("http", "bearer")
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            route = f"{method.upper()} {path}"
            public = route in GATEWAY_ACCESS["public"]
            expected = None if public else [{"bearerAuth": []}]
            assert operation.get("security") == expected, route
