"""Every TACTIC path the gateway calls exists, and every TACTIC route has a caller."""

import ast
import re
from pathlib import Path

import off_key_api_gateway
import pytest
from off_key_core.config.service_auth import get_service_auth_settings
from off_key_tactic_middleware.main import create_app

from tests.support.env import AUTH_ENVIRONMENT, EMAIL_ENVIRONMENT, set_environment
from tests.support.runtime_cache import reset_runtime_caches_for_tests

GATEWAY = Path(off_key_api_gateway.__file__).parent
# Call name -> (index of the method argument, index and keyword of the path
# argument, default path, TACTIC prefix the helper adds).
CALL_SHAPES = {
    "request": (0, 1, "endpoint", None, ""),
    "forward": (1, 2, "path", None, "/api/v1/monitors"),
    "member_request": (0, 1, "path", None, "/api/v1/members"),
    "system_request": (0, 2, "path", "", "/api/v1/system"),
}
# TACTIC routes the gateway deliberately never calls.
INTERNAL_ONLY = {
    ("GET", "/api/v1/orchestration/radar/models/"): "operator API",
    ("GET", "/api/v1/models/info/{model_type}"): "operator API",
    ("POST", "/api/v1/models/validate"): "operator API",
    ("POST", "/api/v1/models/create-instance"): "operator API",
    ("GET", "/api/v1/models/categories/models"): "operator API",
    ("GET", "/api/v1/models/health"): "operator API",
    ("GET", "/api/v1/admin/models/"): "operator API",
    ("PUT", "/api/v1/admin/models/{model_type}"): "operator API",
    ("DELETE", "/api/v1/admin/models/{model_type}"): "operator API",
    ("POST", "/api/v1/admin/models/{model_type}/test"): "operator API",
}


def _literal(node):
    """Render a path literal, replacing each interpolation with one segment."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else "x"
            for part in node.values
        )
    raise AssertionError(f"Unrecognised TACTIC call argument: {ast.dump(node)}")


def _argument(call, index, keyword, default=None):
    for item in call.keywords:
        if item.arg == keyword:
            return _literal(item.value)
    if index < len(call.args):
        return _literal(call.args[index])
    if default is None:
        raise AssertionError(f"TACTIC call without {keyword}: {ast.dump(call)}")
    return default


def _name(call):
    function = call.func
    if isinstance(function, ast.Attribute) and function.attr == "request":
        # The facade's own HTTP session call is the transport, not a route.
        owner = function.value
        return (
            None if isinstance(owner, ast.Name) and owner.id == "session" else "request"
        )
    if isinstance(function, ast.Name) and function.id in CALL_SHAPES:
        return function.id
    return None


def gateway_calls():
    calls = set()
    for path in GATEWAY.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if function.name in CALL_SHAPES:
                # The helpers' own call takes its path from their caller.
                continue
            for call in ast.walk(function):
                if not isinstance(call, ast.Call) or not (name := _name(call)):
                    continue
                method_index, path_index, keyword, default, prefix = CALL_SHAPES[name]
                method = _argument(call, method_index, "method")
                endpoint = _argument(call, path_index, keyword, default)
                calls.add((method, prefix + endpoint.split("?", 1)[0]))
    return calls


@pytest.fixture(scope="module")
def tactic_routes():
    environment = {
        **AUTH_ENVIRONMENT,
        **EMAIL_ENVIRONMENT,
        "INTERNAL_API_SECRET": "test-internal-service-secret-123456789",
        "ANOMALY_ALERT_RECIPIENTS": "admin@example.com",
    }
    with pytest.MonkeyPatch.context() as monkeypatch:
        set_environment(monkeypatch, environment)
        monkeypatch.setattr(
            "off_key_core.config.env.load_dotenv", lambda *args, **kwargs: False
        )
        reset_runtime_caches_for_tests()
        get_service_auth_settings.cache_clear()
        app = create_app()
        reset_runtime_caches_for_tests()
        get_service_auth_settings.cache_clear()
    # TACTIC hides no route from its schema, so the schema lists them all.
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/v1")
        for method in operations
    }


def _matches(template, path):
    pattern = re.sub(r"\{[^}]+\}", "[^/]+", template)
    return re.fullmatch(pattern, path) is not None


def test_every_gateway_call_targets_a_tactic_route(tactic_routes):
    calls = gateway_calls()
    assert len(calls) > 50
    missing = sorted(
        (method, path)
        for method, path in calls
        if not any(
            method == route_method and _matches(template, path)
            for route_method, template in tactic_routes
        )
    )
    assert not missing


def test_every_tactic_route_has_a_gateway_caller(tactic_routes):
    calls = gateway_calls()
    unused = sorted(
        (method, template)
        for method, template in tactic_routes
        if (method, template) not in INTERNAL_ONLY
        and not any(
            method == call_method and _matches(template, path)
            for call_method, path in calls
        )
    )
    assert not unused
    assert set(INTERNAL_ONLY) <= tactic_routes
