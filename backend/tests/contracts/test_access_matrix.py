"""Who may call each route, in one readable table per service.

TACTIC trusts only the gateway's service key; on top of that a route may
require the signed-in member or one permission. The gateway authenticates
members itself; on "monitors" and "alarms" every member reads and changes need
manage_monitors or manage_alarms. A new route fails these tests until it is
added to its table, so a change to access is always a deliberate, reviewed edit.
"""

from collections import defaultdict

import pytest
from fastapi.routing import iter_route_contexts
from off_key_api_gateway.api import access
from off_key_api_gateway.app import build_app
from off_key_api_gateway.settings import AppSettings
from off_key_core.auth.permissions import Permission
from off_key_tactic_middleware.api import collection_auth
from off_key_tactic_middleware.api.service_auth import require_gateway
from off_key_tactic_middleware.main import create_app

TACTIC_ACCESS = {
    "public": {
        "GET /docs",
        "GET /docs/oauth2-redirect",
        "GET /health",
        "GET /ready",
        "GET /redoc",
    },
    "service": {
        "GET /api/v1/data/alarms",
        "POST /api/v1/data/alarms",
        "GET /api/v1/data/alarms/count",
        "POST /api/v1/data/alarms/query",
        "DELETE /api/v1/data/alarms/{alarm_id}",
        "POST /api/v1/data/auth/login",
        "GET /api/v1/data/devices",
        "GET /api/v1/data/devices/{device_id}/readings",
        "GET /api/v1/data/evidence",
        "GET /api/v1/data/evidence/chart",
        "GET /api/v1/data/readings/{stream_id}/measurements",
        "GET /api/v1/data/readings/{stream_id}/measurements/buckets",
        "GET /api/v1/data/users/{user_id}/favorites",
        "POST /api/v1/data/users/{user_id}/favorites",
        "DELETE /api/v1/data/users/{user_id}/favorites",
        "POST /api/v1/members/accept-invitation",
        "POST /api/v1/members/request-password-reset",
        "POST /api/v1/members/reset-password",
        "POST /api/v1/members/sessions/refresh",
        "POST /api/v1/members/sessions/revoke",
        "POST /api/v1/members/sessions/revoke-access",
        "GET /api/v1/models/",
        "GET /api/v1/orchestration/radar/services/",
        "POST /api/v1/orchestration/radar/services/start/",
        "DELETE /api/v1/orchestration/radar/services/{service_id}",
        "GET /api/v1/orchestration/radar/services/{service_id}",
        "POST /api/v1/orchestration/radar/services/{service_id}/stop",
        "PATCH /api/v1/orchestration/radar/services/{service_id}/label",
    },
    "member": {
        "GET /api/v1/members/me",
        "POST /api/v1/members/sessions",
        "GET /api/v1/roles",
        "GET /api/v1/monitors/pipeline-activations/{activation_id}",
        "GET /api/v1/monitors/pipeline-blocks",
        "GET /api/v1/monitors/pipelines",
        "GET /api/v1/monitors/pipelines/catalog",
        "GET /api/v1/monitors/pipelines/forecast-models",
        "GET /api/v1/monitors/pipelines/{pipeline_id}",
        "GET /api/v1/monitors/pipelines/{pipeline_id}/revisions",
        "GET /api/v1/monitors/pipelines/{pipeline_id}/revisions/{revision_id}",
        "GET /api/v1/monitors/pipelines/{pipeline_id}/revisions/{revision_id}/metadata",
        "GET /api/v1/monitors/workspace",
        "GET /api/v1/monitors/{service_id}/pipeline",
        "GET /api/v1/monitors/{service_id}/pipeline-history",
        "GET /api/v1/monitors/{service_id}/pipeline-timeline",
        "GET /api/v1/monitors/{service_id}/pipeline-metadata",
        "GET /api/v1/monitors/{service_id}/pipeline-state",
        "GET /api/v1/system",
        "POST /api/v1/system/collection/status",
        "GET /api/v1/system/health",
        "GET /api/v1/system/live",
        "GET /api/v1/system/revisions",
        "GET /api/v1/system/storage",
    },
    "manage_members": {
        "GET /api/v1/members",
        "POST /api/v1/members/invitations",
        "DELETE /api/v1/members/{user_id}",
        "PATCH /api/v1/members/{user_id}",
        "POST /api/v1/roles",
        "DELETE /api/v1/roles/{role_id}",
        "PATCH /api/v1/roles/{role_id}",
    },
    "use_dojo": {
        "GET /api/v1/dojo/datasets",
        "POST /api/v1/dojo/datasets/csv",
        "POST /api/v1/dojo/datasets/history",
        "DELETE /api/v1/dojo/datasets/{dataset_id}",
        "GET /api/v1/dojo/datasets/{dataset_id}",
        "PATCH /api/v1/dojo/datasets/{dataset_id}",
        "GET /api/v1/dojo/datasets/{dataset_id}/series/{series_id}/points",
        "GET /api/v1/dojo/datasets/{dataset_id}/comparison",
        "GET /api/v1/dojo/datasets/{dataset_id}/labels",
        "GET /api/v1/dojo/datasets/{dataset_id}/label-suggestions",
        "POST /api/v1/dojo/datasets/{dataset_id}/labels",
        "POST /api/v1/dojo/datasets/{dataset_id}/labels/batch",
        "DELETE /api/v1/dojo/datasets/{dataset_id}/labels/{label_id}",
        "PATCH /api/v1/dojo/datasets/{dataset_id}/labels/{label_id}",
        "GET /api/v1/dojo/runs",
        "POST /api/v1/dojo/runs",
        "DELETE /api/v1/dojo/runs/{run_id}",
        "GET /api/v1/dojo/runs/{run_id}",
        "POST /api/v1/dojo/runs/{run_id}/cancel",
        "GET /api/v1/dojo/runs/{run_id}/metrics",
        "GET /api/v1/dojo/runs/{run_id}/calibration",
        "GET /api/v1/dojo/runs/{run_id}/results",
    },
    "manage_monitors": {
        # Also behind the Dojo router's use_dojo; see test_dojo_promotion.
        "POST /api/v1/dojo/runs/{run_id}/promote",
        "POST /api/v1/monitors/pipeline-activations",
        "DELETE /api/v1/monitors/pipeline-activations/{activation_id}",
        "POST /api/v1/monitors/pipeline-blocks",
        "DELETE /api/v1/monitors/pipeline-blocks/{block_id}",
        "POST /api/v1/monitors/pipelines",
        "POST /api/v1/monitors/pipelines/apply",
        "POST /api/v1/monitors/pipelines/forecast-models/downloads",
        "POST /api/v1/monitors/pipelines/validate",
        "PATCH /api/v1/monitors/pipelines/{pipeline_id}",
        "PUT /api/v1/monitors/pipelines/{pipeline_id}/draft",
        "POST /api/v1/monitors/pipelines/{pipeline_id}/revisions",
        "POST /api/v1/monitors/pipelines/{pipeline_id}/validate",
        "PUT /api/v1/monitors/{service_id}/pipeline-layout",
    },
    "manage_sources": {
        "PUT /api/v1/system",
        "PUT /api/v1/system/collection",
        "POST /api/v1/system/collection/preview",
        "POST /api/v1/system/connections/check",
        "POST /api/v1/system/connections/reconnect",
        "POST /api/v1/system/live/leases",
        "DELETE /api/v1/system/live/leases/{lease_id}",
        "PUT /api/v1/system/live/leases/{lease_id}",
    },
}

GATEWAY_ACCESS = {
    "public": {
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
        "POST /v1/alarms/query",
        "GET /v1/detectors",
        "GET /v1/evidence",
        "GET /v1/evidence/chart",
        "GET /v1/pipeline-components",
        "GET /v1/devices",
        "GET /v1/devices/{device_id}/readings",
        "DELETE /v1/favorites",
        "GET /v1/favorites",
        "POST /v1/favorites",
        "GET /v1/me",
        "GET /v1/permissions",
        "GET /v1/roles",
        "POST /v1/brokers/check",
        "POST /v1/brokers/{broker_id}/reconnect",
        "GET /v1/catalogue",
        "PUT /v1/catalogue",
        "GET /v1/catalogue/revisions",
        "GET /v1/live/measurements",
        "POST /v1/live/views",
        "DELETE /v1/live/views/{view_id}",
        "POST /v1/live/views/{view_id}/renew",
        "PUT /v1/recording",
        "GET /v1/recording/health",
        "POST /v1/recording/preview",
        "POST /v1/recording/status",
        "GET /v1/storage",
        "GET /v1/readings/{reading_id}/measurements",
        "GET /v1/readings/{reading_id}/measurements/buckets",
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
        "GET /v1/pipelines",
        "POST /v1/pipelines",
        "POST /v1/pipelines/apply",
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
    },
    "manage_members": {
        "POST /v1/invitations",
        "GET /v1/members",
        "DELETE /v1/members/{member_id}",
        "PATCH /v1/members/{member_id}",
        "POST /v1/roles",
        "DELETE /v1/roles/{role_id}",
        "PATCH /v1/roles/{role_id}",
    },
}


def _calls(dependant):
    yield dependant.call
    for dependency in dependant.dependencies:
        yield from _calls(dependency)


def _routes(app):
    """(method, path, dependency callables), router-level dependencies included."""
    for context in iter_route_contexts(app.routes):
        # Since FastAPI 0.140 an included router's dependencies live on the
        # effective route context rather than on the original APIRoute.
        effective = getattr(context, "_route_context", None)
        dependant = getattr(effective, "dependant", None) or getattr(
            context.route, "dependant", None
        )
        if dependant is None:
            continue
        for method in context.methods or ():
            if method != "HEAD":
                yield f"{method} {context.path}", set(_calls(dependant))


def _classify(app, levels):
    found = defaultdict(set)
    for route, calls in _routes(app):
        level = next((name for name, call in levels if call in calls), "public")
        found[level].add(route)
    return dict(found)


def test_tactic_routes_match_the_access_table(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SECRET", "test-private-api-credential-123456789")
    found = _classify(
        create_app(),
        [
            *(
                (permission.value, collection_auth.require_permission(permission))
                for permission in Permission
            ),
            ("member", collection_auth.current_member),
            ("service", require_gateway),
        ],
    )
    assert found == TACTIC_ACCESS


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
            ("member", access.current_member),
        ],
    )
    assert found == GATEWAY_ACCESS


@pytest.mark.parametrize("route", sorted(GATEWAY_ACCESS["public"]))
def test_public_gateway_routes_are_documentation_health_or_sign_in(route):
    path = route.split()[1]
    assert path in {
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/health",
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
