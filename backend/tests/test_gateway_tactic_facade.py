"""The gateway's TACTIC client against a real HTTP server: headers and error mapping.

Retry safety for failed connections lives in test_gateway_security_hardening.py.
"""

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestServer
from off_key_api_gateway.facades.tactic import Tactic, TacticError, path_segment
from off_key_core.config.logs import correlation_id
from off_key_core.config.service_auth import get_service_auth_settings

SERVICE_KEY = "test-internal-service-secret-123456789"


@pytest_asyncio.fixture
async def serve(monkeypatch):
    """Point a fresh facade at a loopback server answering with one response."""
    monkeypatch.setenv("INTERNAL_API_SECRET", SERVICE_KEY)
    get_service_auth_settings.cache_clear()
    facade = Tactic()
    servers = []

    async def start(status=200, text='{"ok": true}', content_type="application/json"):
        received = {}

        async def handler(request: web.Request) -> web.Response:
            received.update(
                method=request.method,
                path=request.path,
                query=dict(request.query),
                service_key=request.headers.get("X-Off-Key-Service-Key"),
                authorization=request.headers.get("Authorization"),
                correlation_id=request.headers.get("X-Correlation-ID"),
                body=await request.json() if request.can_read_body else None,
            )
            return web.Response(status=status, text=text, content_type=content_type)

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handler)
        server = TestServer(app, host="127.0.0.1")
        await server.start_server()
        servers.append(server)
        facade.base_url = str(server.make_url("")).rstrip("/")
        return facade, received

    yield start
    await facade.close()
    for server in servers:
        await server.close()
    get_service_auth_settings.cache_clear()


async def test_requests_carry_the_service_key_caller_credentials_and_clean_query(
    serve,
):
    facade, received = await serve()

    result = await facade.request(
        "POST",
        "/api/v1/monitors/monitor-1",
        json_data={"label": "Line 1"},
        params={"draft": True, "archived": False, "cursor": None, "limit": 5},
        headers={"Authorization": "Bearer member-token"},
    )

    assert result == {"ok": True}
    assert received == {
        "method": "POST",
        "path": "/api/v1/monitors/monitor-1",
        "query": {"draft": "true", "archived": "false", "limit": "5"},
        "service_key": SERVICE_KEY,
        "authorization": "Bearer member-token",
        "correlation_id": None,
        "body": {"label": "Line 1"},
    }


async def test_requests_forward_the_current_correlation_id(serve):
    facade, received = await serve()
    token = correlation_id.set("request-123")
    try:
        await facade.request("GET", "/api/v1/system")
    finally:
        correlation_id.reset(token)

    assert received["correlation_id"] == "request-123"


@pytest.mark.parametrize(
    ("status", "text", "content_type", "message", "body"),
    [
        (
            404,
            '{"detail": "Monitor not found"}',
            "application/json",
            "Monitor not found",
            {"detail": "Monitor not found"},
        ),
        (
            500,
            "upstream exploded",
            "text/plain",
            "upstream exploded",
            "upstream exploded",
        ),
        (
            502,
            '{"detail": "bad gateway"}',
            "text/plain",
            "bad gateway",
            {"detail": "bad gateway"},
        ),
        (503, "", "text/plain", "HTTP 503", ""),
    ],
    ids=["json_detail", "plain_text", "untyped_json", "empty"],
)
async def test_error_responses_raise_typed_errors_with_downstream_detail(
    serve, status, text, content_type, message, body
):
    facade, _ = await serve(status, text, content_type)

    with pytest.raises(TacticError) as raised:
        await facade.request("GET", "/api/v1/monitors")

    assert raised.value.status == status
    assert str(raised.value) == f"TACTIC service error: {message}"
    assert raised.value.body == body


async def test_unexpected_client_failures_become_tactic_errors(serve):
    facade, _ = await serve()

    with pytest.raises(TacticError, match="TACTIC request error") as raised:
        # A body that cannot be serialized fails before anything is sent.
        await facade.request("POST", "/api/v1/monitors", json_data={1, 2})

    assert raised.value.status is None


@pytest.mark.parametrize("identifier", ["", ".", "..", "a/b", "a\\b"])
def test_path_segments_reject_traversal(identifier):
    with pytest.raises(TacticError) as raised:
        path_segment(identifier)

    assert raised.value.status == 422


def test_path_segments_are_percent_encoded():
    assert path_segment("member+1@example.com") == "member%2B1%40example.com"
