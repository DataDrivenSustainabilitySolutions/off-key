"""Who may call each route, in one readable table per service.

TACTIC trusts only the gateway's service key; on top of that a route may
require the signed-in member or an administrator. The gateway authenticates
members itself; "operational" lets every member read and only administrators
write. A new route fails these tests until it is added to its table, so a
change to access is always a deliberate, reviewed edit.
"""

from collections import defaultdict

import pytest
from fastapi.routing import iter_route_contexts
from off_key_api_gateway.api import access
from off_key_api_gateway.app import build_app
from off_key_api_gateway.settings import AppSettings
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
        "POST /api/v1/data/anomalies",
        "GET /api/v1/data/anomalies/count",
        "DELETE /api/v1/data/anomalies/{anomaly_id}",
        "GET /api/v1/data/anomalies/{charger_id}",
        "POST /api/v1/data/auth/login",
        "GET /api/v1/data/chargers",
        "GET /api/v1/data/chargers/active/ids",
        "GET /api/v1/data/monitoring-evidence/{charger_id}",
        "GET /api/v1/data/monitoring-evidence/{charger_id}/chart",
        "GET /api/v1/data/telemetry/{charger_id}",
        "GET /api/v1/data/telemetry/{charger_id}/range",
        "GET /api/v1/data/telemetry/{charger_id}/types",
        "GET /api/v1/data/users/{user_id}/favorites",
        "POST /api/v1/data/users/{user_id}/favorites",
        "DELETE /api/v1/data/users/{user_id}/favorites/{charger_id}",
        "POST /api/v1/members/accept-invitation",
        "POST /api/v1/members/request-password-reset",
        "POST /api/v1/members/reset-password",
        "POST /api/v1/members/sessions/refresh",
        "POST /api/v1/members/sessions/revoke",
        "GET /api/v1/models/",
        "GET /api/v1/orchestration/radar/services/",
        "GET /api/v1/orchestration/radar/services/details/",
        "POST /api/v1/orchestration/radar/services/start/",
        "DELETE /api/v1/orchestration/radar/services/stop/",
        "DELETE /api/v1/orchestration/radar/services/{service_id}",
        "PATCH /api/v1/orchestration/radar/services/{service_id}/label",
    },
    "member": {
        "GET /api/v1/members/me",
        "POST /api/v1/members/sessions",
        "GET /api/v1/monitors/pipeline-activations/{activation_id}",
        "GET /api/v1/monitors/pipelines",
        "GET /api/v1/monitors/pipelines/catalog",
        "GET /api/v1/monitors/pipelines/{pipeline_id}",
        "GET /api/v1/monitors/pipelines/{pipeline_id}/revisions",
        "GET /api/v1/monitors/pipelines/{pipeline_id}/revisions/{revision_id}",
        "GET /api/v1/monitors/pipelines/{pipeline_id}/revisions/{revision_id}/metadata",
        "GET /api/v1/monitors/workspace",
        "GET /api/v1/monitors/{service_id}/pipeline",
        "GET /api/v1/monitors/{service_id}/pipeline-history",
        "GET /api/v1/monitors/{service_id}/pipeline-metadata",
        "GET /api/v1/monitors/{service_id}/pipeline-state",
        "GET /api/v1/system",
        "POST /api/v1/system/collection/status",
        "GET /api/v1/system/health",
        "GET /api/v1/system/live",
        "GET /api/v1/system/revisions",
        "GET /api/v1/system/storage",
    },
    "admin": {
        "GET /api/v1/members",
        "POST /api/v1/members/invitations",
        "DELETE /api/v1/members/{user_id}",
        "PUT /api/v1/members/{user_id}",
        "POST /api/v1/monitors/pipeline-activations",
        "DELETE /api/v1/monitors/pipeline-activations/{activation_id}",
        "POST /api/v1/monitors/pipelines",
        "POST /api/v1/monitors/pipelines/apply",
        "POST /api/v1/monitors/pipelines/validate",
        "PATCH /api/v1/monitors/pipelines/{pipeline_id}",
        "PUT /api/v1/monitors/pipelines/{pipeline_id}/draft",
        "POST /api/v1/monitors/pipelines/{pipeline_id}/revisions",
        "POST /api/v1/monitors/pipelines/{pipeline_id}/validate",
        "PUT /api/v1/monitors/{service_id}/pipeline-layout",
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
        "POST /v1/auth/forgot-password",
        "POST /v1/auth/login",
        "POST /v1/auth/logout",
        "POST /v1/auth/refresh",
        "POST /v1/auth/register",
        "POST /v1/auth/reset-password",
        "GET /v1/auth/verify-email",
        "GET /v1/demo",
    },
    "member": {
        "GET /v1/chargers/active",
        "GET /v1/chargers/active/id",
        "GET /v1/chargers/available",
        "DELETE /v1/favorites",
        "GET /v1/favorites",
        "POST /v1/favorites",
        "GET /v1/members/me",
        "GET /v1/system",
        "PUT /v1/system",
        "PUT /v1/system/collection",
        "POST /v1/system/collection/preview",
        "POST /v1/system/collection/status",
        "POST /v1/system/connections/check",
        "POST /v1/system/connections/reconnect",
        "GET /v1/system/health",
        "GET /v1/system/live",
        "POST /v1/system/live/leases",
        "DELETE /v1/system/live/leases/{lease_id}",
        "PUT /v1/system/live/leases/{lease_id}",
        "GET /v1/system/revisions",
        "GET /v1/system/storage",
        "GET /v1/telemetry/{charger_id}/data",
        "GET /v1/telemetry/{charger_id}/range",
        "GET /v1/telemetry/{charger_id}/type",
    },
    "operational": {
        "GET /v1/anomalies",
        "POST /v1/anomalies",
        "GET /v1/anomalies/count",
        "DELETE /v1/anomalies/{anomaly_id}",
        "GET /v1/monitors",
        "GET /v1/monitors/all",
        "GET /v1/monitors/evidence",
        "GET /v1/monitors/evidence/chart",
        "GET /v1/monitors/models",
        "POST /v1/monitors/pipeline-activations",
        "DELETE /v1/monitors/pipeline-activations/{activation_id}",
        "GET /v1/monitors/pipeline-activations/{activation_id}",
        "GET /v1/monitors/pipelines",
        "POST /v1/monitors/pipelines",
        "POST /v1/monitors/pipelines/apply",
        "GET /v1/monitors/pipelines/catalog",
        "POST /v1/monitors/pipelines/validate",
        "GET /v1/monitors/pipelines/{pipeline_id}",
        "PATCH /v1/monitors/pipelines/{pipeline_id}",
        "PUT /v1/monitors/pipelines/{pipeline_id}/draft",
        "GET /v1/monitors/pipelines/{pipeline_id}/revisions",
        "POST /v1/monitors/pipelines/{pipeline_id}/revisions",
        "GET /v1/monitors/pipelines/{pipeline_id}/revisions/{revision_id}",
        "GET /v1/monitors/pipelines/{pipeline_id}/revisions/{revision_id}/metadata",
        "POST /v1/monitors/pipelines/{pipeline_id}/validate",
        "POST /v1/monitors/start",
        "DELETE /v1/monitors/stop",
        "GET /v1/monitors/workspace",
        "DELETE /v1/monitors/{service_id}",
        "PATCH /v1/monitors/{service_id}/label",
        "GET /v1/monitors/{service_id}/pipeline",
        "GET /v1/monitors/{service_id}/pipeline-history",
        "PUT /v1/monitors/{service_id}/pipeline-layout",
        "GET /v1/monitors/{service_id}/pipeline-metadata",
        "GET /v1/monitors/{service_id}/pipeline-state",
    },
    "admin": {
        "GET /v1/members",
        "POST /v1/members/invitations",
        "DELETE /v1/members/{user_id}",
        "PUT /v1/members/{user_id}",
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
            ("admin", collection_auth.require_admin),
            ("member", collection_auth.current_member),
            ("service", require_gateway),
        ],
    )
    assert found == TACTIC_ACCESS


def test_gateway_routes_match_the_access_table():
    found = _classify(
        build_app(AppSettings(APP_NAME="off-key-test")),
        [
            ("admin", access.require_admin),
            ("operational", access.operational_access),
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
        "/v1/demo",
    } or (path.startswith("/v1/auth/"))
