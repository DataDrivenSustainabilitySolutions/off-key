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

from ...provider import get_agent_service
from ...services.accounts.agents import AgentService
from ..collection_auth import current_agent, current_member, require_permission
from ..errors import DomainErrorRoute

router = APIRouter(prefix="/agents", tags=["agents"], route_class=DomainErrorRoute)
manage_members = require_permission(Permission.manage_members)

# Dependency overrides in tests address this name; it is the provider.
agent_service = get_agent_service


@router.get("/me", response_model=AgentProfile, openapi_extra=OPEN_TO_AGENTS)
async def me(agent: Agent = Depends(current_agent)):
    return agent


@router.get(
    "", response_model=list[AgentProfile], dependencies=[Depends(manage_members)]
)
async def list_agents(service: AgentService = Depends(agent_service)):
    return await service.list()


@router.post(
    "",
    response_model=AgentCreated,
    status_code=201,
    dependencies=[Depends(manage_members)],
)
async def create_agent(
    change: AgentCreate,
    actor: User = Depends(current_member),
    service: AgentService = Depends(agent_service),
):
    agent, key = await service.create(change, actor)
    return AgentCreated.model_validate(
        AgentProfile.model_validate(agent).model_dump() | {"key": key}
    )


@router.patch(
    "/{agent_id}",
    response_model=AgentProfile,
    dependencies=[Depends(manage_members)],
)
async def update_agent(
    agent_id: int,
    change: AgentUpdate,
    actor: User = Depends(current_member),
    service: AgentService = Depends(agent_service),
):
    return await service.update(agent_id, change, actor)


@router.delete("/{agent_id}", status_code=204, dependencies=[Depends(manage_members)])
async def revoke_agent(
    agent_id: int,
    actor: User = Depends(current_member),
    service: AgentService = Depends(agent_service),
):
    await service.revoke(agent_id, actor)
    return Response(status_code=204)
