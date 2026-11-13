"""The gateway as an MCP server, at `/v1/mcp`.

An agent connects with its key and finds the operations a key may call as
tools (`mcp_tools`). A tool calls the gateway's own routes in-process, with the
key it was called with, so the routes go on deciding who may do what and how
often. Nothing here holds state between requests: every request carries its
key, and any replica answers it.
"""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

import httpx2
import mcp_types as types
from fastapi import FastAPI
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel.server import Server
from mcp.server.transport_security import TransportSecuritySettings
from off_key_core.config.logs import correlation_headers
from off_key_core.schemas.agents import AgentProfile
from pydantic import ValidationError
from starlette.datastructures import State
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from .mcp_tools import INSTRUCTIONS, TOOLS, Api, ApiRefusal, Tool
from .rate_limiter import client_ip

MCP_PATH = "/v1/mcp"


def _offered(tool: Tool, agent: AgentProfile) -> bool:
    return agent.may_start or not tool.starts


def _caller(ctx: ServerRequestContext) -> State:
    """What the door left on the HTTP request, which is the only way in."""
    return cast(Request, ctx.request).state


async def _list_tools(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    agent: AgentProfile = _caller(ctx).agent
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name=tool.name,
                description=tool.description,
                input_schema=tool.schema(),
                annotations=types.ToolAnnotations(
                    read_only_hint=not tool.changes,
                    destructive_hint=False,
                    open_world_hint=False,
                ),
            )
            for tool in TOOLS.values()
            if _offered(tool, agent)
        ]
    )


def _answer(said: Any, refused: bool = False) -> types.CallToolResult:
    text = said if isinstance(said, str) else json.dumps(said, separators=(",", ":"))
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)], is_error=refused
    )


def _problems(error: ValidationError) -> str:
    """Where each argument is wrong and how, without echoing what was sent."""
    return "; ".join(
        f"{'.'.join(str(part) for part in problem['loc']) or 'arguments'}: "
        f"{problem['msg']}"
        for problem in error.errors(include_url=False, include_input=False)
    )


async def _call_tool(
    ctx: ServerRequestContext, params: types.CallToolRequestParams
) -> types.CallToolResult:
    state = _caller(ctx)
    tool = TOOLS.get(params.name)
    if tool is None or not _offered(tool, state.agent):
        return _answer(f"There is no tool called {params.name}", refused=True)
    try:
        arguments = tool.arguments.model_validate(params.arguments or {})
    except ValidationError as error:
        return _answer(_problems(error), refused=True)
    try:
        return _answer(await tool.call(state.api, arguments))
    except ApiRefusal as refusal:
        # In the API's own words, which say what to change.
        return _answer(refusal.detail, refused=True)


class _Door:
    """Let an agent's key in, and hand its request to the MCP server."""

    # The rate limiter names every route after its endpoint.
    __name__ = "mcp"

    def __init__(self, client: httpx2.AsyncClient, serve):
        self.client = client
        self.serve = serve

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope)
        # The routes count the calls of a tool against the agent's own address.
        headers = {"X-Forwarded-For": client_ip(request), **correlation_headers()}
        if authorization := request.headers.get("authorization"):
            headers["Authorization"] = authorization
        api = Api(self.client, headers)
        try:
            agent = AgentProfile.model_validate(await api.get("/v1/agents/me"))
        except ApiRefusal as refusal:
            answer = JSONResponse({"detail": refusal.detail}, refusal.status)
            if refusal.status == 401:
                answer.headers["WWW-Authenticate"] = "Bearer"
            if refusal.retry_after:
                answer.headers["Retry-After"] = refusal.retry_after
            await answer(scope, receive, send)
            return
        request.state.api = api
        request.state.agent = agent
        await self.serve(scope, receive, send)


def add_mcp(app: FastAPI):
    """Add `/v1/mcp` to the gateway.

    Returns what the app's lifespan runs for as long as the app does.
    """
    server = Server(
        "off-key",
        title="Monitoring designs",
        instructions=INSTRUCTIONS,
        on_list_tools=_list_tools,
        on_call_tool=_call_tool,
    )
    # One JSON answer per request and no session, so a proxy has nothing to
    # hold open and replicas need not share anything. The key is the access
    # check; a browser cannot send it for another site, so the check on the
    # Host header has nothing to add behind a proxy that rewrites it.
    server.streamable_http_app(
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )
    sessions = server.session_manager
    client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://gateway",
        # In-process calls: a proxy named in the environment is not for them,
        # and compressing an answer only to read it again costs for nothing.
        trust_env=False,
        headers={"Accept-Encoding": "identity"},
    )
    app.router.routes.append(
        Route(
            MCP_PATH, endpoint=_Door(client, sessions.handle_request), methods=["POST"]
        )
    )

    @asynccontextmanager
    async def running() -> AsyncGenerator[None]:
        async with client, sessions.run():
            yield

    return running
