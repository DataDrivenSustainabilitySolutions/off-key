"""The gateway's OpenAPI document is a contract that agents and generated
clients can use without reading the source: each operation is named after its
handler, described, and declares the bearer scheme instead of asking for an
Authorization parameter.
"""

import pytest
from fastapi.testclient import TestClient
from off_key_api_gateway.app import build_app
from off_key_api_gateway.settings import AppSettings


@pytest.fixture(scope="module")
def schema():
    return build_app(AppSettings(APP_NAME="off-key-test")).openapi()


def operations(schema):
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            yield f"{method.upper()} {path}", operation


def test_operation_ids_are_unique_handler_names(schema):
    ids = [operation["operationId"] for _, operation in operations(schema)]
    assert len(ids) == len(set(ids))
    # FastAPI's default appends the path and method; a handler name stays short.
    assert [name for name in ids if "_v1_" in name or name.endswith("_get")] == []


def test_every_operation_is_described(schema):
    undescribed = [
        route
        for route, operation in operations(schema)
        if not operation.get("description", "").strip()
    ]
    assert undescribed == []


def test_every_tag_is_described(schema):
    described = {tag["name"] for tag in schema["tags"] if tag.get("description")}
    used = {tag for _, operation in operations(schema) for tag in operation["tags"]}
    assert used <= described


def test_no_operation_asks_for_the_token_as_a_parameter(schema):
    leaked = [
        route
        for route, operation in operations(schema)
        for parameter in operation.get("parameters", [])
        if parameter["in"] == "header" and parameter["name"].lower() == "authorization"
    ]
    assert leaked == []


def test_the_api_prefix_is_named_as_the_server():
    """Deployments start the gateway with --root-path /api behind the proxy."""
    app = build_app(AppSettings(APP_NAME="off-key-test"))
    client = TestClient(app, root_path="/api")
    assert client.get("/openapi.json").json()["servers"] == [{"url": "/api"}]
    assert "/api/openapi.json" in client.get("/docs").text
