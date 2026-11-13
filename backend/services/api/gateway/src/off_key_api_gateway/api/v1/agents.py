"""Agents: callers that sign in with a key in place of a password."""

from fastapi import APIRouter, Depends, Response
from off_key_core.auth.agents import OPEN_TO_AGENTS
from off_key_core.auth.permissions import Permission
from off_key_core.db.models import Agent, User
from off_key_core.schemas.agents import (
    AgentCreate,
    AgentCreated,
    AgentProfile,
    AgentUpdate,
)
from off_key_tactic_middleware.services.accounts.agents import AgentService

from ...providers import get_agent_service
from ..access import current_agent, require_permission
from ..errors import DomainErrorRoute

router = APIRouter(route_class=DomainErrorRoute)
manage_members = require_permission(Permission.manage_members)


@router.get("/me", response_model=AgentProfile, openapi_extra=OPEN_TO_AGENTS)
async def get_agent(agent: Agent = Depends(current_agent)):
    """The agent whose key this is, and whether it may start monitoring services.

    Only a key can ask this; a member reads `GET /v1/me`.
    """
    return agent


@router.get(
    "", response_model=list[AgentProfile], dependencies=[Depends(manage_members)]
)
async def list_agents(service: AgentService = Depends(get_agent_service)):
    """Every agent that holds a key. Needs `manage_members`."""
    return await service.list()


@router.post("", response_model=AgentCreated, status_code=201)
async def create_agent(
    change: AgentCreate,
    actor: User = Depends(manage_members),
    service: AgentService = Depends(get_agent_service),
):
    """Create an agent and its key. Needs `manage_members`.

    The answer carries the key this once. Every key may read, design, test and
    propose; `starts` allows this one to start monitoring services as well, in
    `shadow` only or `live`.
    """
    agent, key = await service.create(change, actor)
    return AgentCreated.model_validate(
        AgentProfile.model_validate(agent).model_dump() | {"key": key}
    )


@router.patch("/{agent_id}", response_model=AgentProfile)
async def update_agent(
    agent_id: int,
    change: AgentUpdate,
    actor: User = Depends(manage_members),
    service: AgentService = Depends(get_agent_service),
):
    """Allow or forbid a key to start monitoring services. Needs `manage_members`."""
    return await service.update(agent_id, change, actor)


@router.delete("/{agent_id}", status_code=204, response_class=Response)
async def revoke_agent(
    agent_id: int,
    actor: User = Depends(manage_members),
    service: AgentService = Depends(get_agent_service),
):
    """Revoke an agent's key, which stops working at once. Needs `manage_members`.

    Monitoring services the agent started keep running.
    """
    await service.revoke(agent_id, actor)
    return Response(status_code=204)
