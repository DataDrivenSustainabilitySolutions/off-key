"""Keys for agents: created and revoked by members who manage members."""

from off_key_core.auth.agents import agent_key_digest, agent_key_hint, new_agent_key
from off_key_core.config.logs import log_security_event
from off_key_core.db.locks import MEMBERSHIP_LOCK
from off_key_core.db.models import Agent, User
from off_key_core.schemas.agents import AgentCreate, AgentUpdate
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain import ConflictError, NotFoundError

MAX_AGENTS = 50


class AgentService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self) -> list[Agent]:
        rows = await self.session.scalars(
            select(Agent).order_by(func.lower(Agent.name), Agent.id)
        )
        return list(rows)

    async def create(self, change: AgentCreate, actor: User) -> tuple[Agent, str]:
        """A new agent and its key. The key is returned once and not kept."""
        # The lock makes the name and the count hold until the commit.
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": MEMBERSHIP_LOCK}
        )
        if await self.session.scalar(
            select(Agent.id).where(func.lower(Agent.name) == change.name.lower())
        ):
            raise ConflictError(
                f"An agent named {change.name} already has a key. Choose another name."
            )
        count = await self.session.scalar(select(func.count()).select_from(Agent))
        if (count or 0) >= MAX_AGENTS:
            raise ConflictError(
                f"{MAX_AGENTS} agents hold a key. Revoke one before creating another."
            )
        key = new_agent_key()
        agent = Agent(
            name=change.name,
            key_hash=agent_key_digest(key),
            key_hint=agent_key_hint(key),
            may_start=change.may_start,
            created_by=actor.email,
        )
        self.session.add(agent)
        await self.session.commit()
        await self.session.refresh(agent)
        log_security_event(
            "agent_key_created",
            actor.email,
            {"agent_id": agent.id, "may_start": agent.may_start},
        )
        return agent, key

    async def update(self, agent_id: int, change: AgentUpdate, actor: User) -> Agent:
        agent = await self._get(agent_id)
        agent.may_start = change.may_start
        await self.session.commit()
        await self.session.refresh(agent)
        log_security_event(
            "agent_access_changed",
            actor.email,
            {"agent_id": agent.id, "may_start": agent.may_start},
        )
        return agent

    async def revoke(self, agent_id: int, actor: User) -> None:
        """Delete the agent, so its key stops working with the next request."""
        agent = await self._get(agent_id)
        await self.session.delete(agent)
        await self.session.commit()
        log_security_event("agent_key_revoked", actor.email, {"agent_id": agent_id})

    async def _get(self, agent_id: int) -> Agent:
        agent = await self.session.get(Agent, agent_id)
        if agent is None:
            raise NotFoundError("Agent not found")
        return agent
