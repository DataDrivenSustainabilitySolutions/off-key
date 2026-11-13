"""Agents: callers that sign in with a key in place of a password."""

from fastapi import APIRouter, Depends, Response
from off_key_core.auth.agents import OPEN_TO_AGENTS
from off_key_core.auth.permissions import Permission
from off_key_core.schemas.agents import (
    AgentCreate,
    AgentCreated,
    AgentProfile,
    AgentUpdate,
)

from ...facades.tactic import tactic
from ..access import current_agent, member_authorization, require_permission
from ..errors import TacticErrorRoute

router = APIRouter(route_class=TacticErrorRoute)
manage_members = require_permission(Permission.manage_members)


async def agent_request(method, path, authorization, body=None):
    return await tactic.request(
        method,
        f"/api/v1/agents{path}",
        json_data=body,
        headers={"Authorization": authorization},
    )


@router.get("/me", response_model=AgentProfile, openapi_extra=OPEN_TO_AGENTS)
async def get_agent(agent: AgentProfile = Depends(current_agent)):
    """The agent whose key this is, and whether it may start monitoring services.

    Only a key can ask this; a member reads `GET /v1/me`.
    """
    return agent


@router.get(
    "", response_model=list[AgentProfile], dependencies=[Depends(manage_members)]
)
async def list_agents(authorization: str = Depends(member_authorization)):
    """Every agent that holds a key. Needs `manage_members`."""
    return await agent_request("GET", "", authorization)


@router.post(
    "",
    response_model=AgentCreated,
    status_code=201,
    dependencies=[Depends(manage_members)],
)
async def create_agent(
    change: AgentCreate, authorization: str = Depends(member_authorization)
):
    """Create an agent and its key. Needs `manage_members`.

    The answer carries the key this once. Every key may read, design, test and
    propose; `may_start` allows this one to start monitoring services as well.
    """
    return await agent_request(
        "POST", "", authorization, change.model_dump(mode="json")
    )


@router.patch(
    "/{agent_id}",
    response_model=AgentProfile,
    dependencies=[Depends(manage_members)],
)
async def update_agent(
    agent_id: int,
    change: AgentUpdate,
    authorization: str = Depends(member_authorization),
):
    """Allow or forbid a key to start monitoring services. Needs `manage_members`."""
    return await agent_request(
        "PATCH", f"/{agent_id}", authorization, change.model_dump(mode="json")
    )


@router.delete(
    "/{agent_id}",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(manage_members)],
)
async def revoke_agent(
    agent_id: int, authorization: str = Depends(member_authorization)
):
    """Revoke an agent's key, which stops working at once. Needs `manage_members`.

    Monitoring services the agent started keep running.
    """
    await agent_request("DELETE", f"/{agent_id}", authorization)
    return Response(status_code=204)
