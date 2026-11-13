"""An agent's key: how it is kept, who hands it out and which routes accept it."""

from types import SimpleNamespace

import pytest
import pytest_asyncio
from off_key_api_gateway.providers import get_pipeline_activations
from off_key_core.auth.agents import (
    AGENT_KEY_PREFIX,
    OPEN_TO_AGENTS,
    STARTS_SERVICES,
    agent_key_digest,
    agent_refusal,
    is_agent_key,
    new_agent_key,
    shadow_refusal,
)
from off_key_core.db.models import Agent, User
from off_key_core.models.pipelines import pipeline_catalog
from off_key_core.schemas.agents import AgentCreate, AgentUpdate
from off_key_tactic_middleware.domain import ConflictError, NotFoundError
from off_key_tactic_middleware.services.accounts.agents import AgentService
from sqlalchemy import select

from tests.support.env import set_auth_env
from tests.support.gateway import gateway_app, returning
from tests.support.http import asgi_client
from tests.support.membership import bootstrap
from tests.support.tokens import access_token


def test_a_key_is_told_from_a_token_and_kept_as_a_digest():
    first, second = new_agent_key(), new_agent_key()
    assert first != second
    assert first.startswith(AGENT_KEY_PREFIX) and len(first) >= 40
    assert is_agent_key(first) and not is_agent_key("eyJhbGciOiJIUzI1NiJ9.e30.x")
    digest = agent_key_digest(first)
    assert digest == agent_key_digest(first) != agent_key_digest(second)
    assert first not in digest and len(digest) == 64


def test_a_route_is_closed_to_keys_until_it_opens_itself():
    def refusal(extra, starts="nothing"):
        return agent_refusal(SimpleNamespace(openapi_extra=extra), starts=starts)

    for closed in (None, {}, {"x-other": "any"}):
        assert "needs a member" in refusal(closed)
        assert "needs a member" in refusal(closed, starts="live")
    assert agent_refusal(None, starts="live") is not None
    assert refusal(OPEN_TO_AGENTS) is None
    assert "may not start" in refusal(STARTS_SERVICES)
    assert refusal(STARTS_SERVICES, starts="shadow") is None
    assert refusal(STARTS_SERVICES, starts="live") is None


def test_a_key_that_starts_in_shadow_only_cannot_start_a_live_service():
    assert "in shadow only" in shadow_refusal(starts="shadow", shadow=False)
    assert shadow_refusal(starts="shadow", shadow=True) is None
    assert shadow_refusal(starts="live", shadow=False) is None
    assert shadow_refusal(starts="live", shadow=True) is None


@pytest_asyncio.fixture
async def keys(member_database, monkeypatch):
    """The members' schema with the agents table."""
    set_auth_env(monkeypatch)
    engine, sessions = member_database
    async with engine.begin() as connection:
        await connection.run_sync(Agent.__table__.create)
    await bootstrap(sessions)
    return sessions


async def admin_of(session) -> User:
    return await session.scalar(select(User).where(User.email == "admin@example.com"))


@pytest.mark.asyncio
async def test_a_member_hands_out_a_key_once_and_revokes_it(keys):
    async with keys() as session:
        service = AgentService(session)
        admin = await admin_of(session)
        agent, key = await service.create(AgentCreate(name=" Night shift "), admin)
        assert (agent.name, agent.starts) == ("Night shift", "nothing")
        assert agent.created_by == "admin@example.com"
        # The table holds the digest and the end of the key, never the key.
        stored = await session.get(Agent, agent.id)
        assert stored.key_hash == agent_key_digest(key) and key.endswith(
            stored.key_hint
        )
        assert key not in (stored.key_hash, stored.key_hint)
        with pytest.raises(ConflictError, match="already has a key"):
            await service.create(AgentCreate(name="night SHIFT"), admin)
        await session.rollback()
        admin = await admin_of(session)
        other, _ = await service.create(
            AgentCreate(name="Auditor", starts="live"), admin
        )
        assert [item.name for item in await service.list()] == [
            "Auditor",
            "Night shift",
        ]
        changed = await service.update(agent.id, AgentUpdate(starts="shadow"), admin)
        assert changed.starts == "shadow"
        await service.revoke(other.id, admin)
        assert [item.name for item in await service.list()] == ["Night shift"]
        with pytest.raises(NotFoundError):
            await service.revoke(other.id, admin)


def api(sessions, activations=None):
    """The API over the members' schema."""
    overrides = {}
    if activations is not None:
        overrides[get_pipeline_activations] = returning(activations)
    return gateway_app(sessions=sessions, overrides=overrides)


def start_request(**fields) -> dict:
    template = pipeline_catalog(True).templates[0]
    return {
        "definition": template.definition.model_dump(mode="json"),
        "bindings": {"value": "reading-1"},
        "display_name": "Pump vibration",
        "idempotency_key": "one",
    } | fields


@pytest.mark.asyncio
async def test_a_key_reaches_only_what_is_open_to_it(keys):
    async with keys() as session:
        admin = await admin_of(session)
        agent, key = await AgentService(session).create(
            AgentCreate(name="Designer"), admin
        )
        token = access_token(admin)
    reached = []

    class Activations:
        async def apply(self, change):
            reached.append((change.display_name, change.shadow))
            raise ValueError("Reached the activation service")

    async with asgi_client(api(keys, Activations())) as client:
        by_key = {"Authorization": f"Bearer {key}"}
        by_member = {"Authorization": f"Bearer {token}"}

        async def call(method, path, headers=by_key, **kwargs):
            response = await client.request(
                method, "/v1" + path, headers=headers, **kwargs
            )
            return response.status_code, response.json() if response.content else None

        status, profile = await call("GET", "/agents/me")
        assert status == 200 and profile["name"] == "Designer"
        assert profile["starts"] == "nothing" and "key" not in profile
        # It reads the catalog and checks a design it holds.
        assert (await call("GET", "/pipeline-components/search?query=smooth"))[0] == 200
        definition = start_request()["definition"]
        status, report = await call(
            "POST", "/pipelines/validate", json={"definition": definition}
        )
        assert status == 200 and "issues" in report
        # Anything not opened to keys needs a member, whatever the key may do.
        for method, path in (
            ("GET", "/me"),
            ("GET", "/agents"),
            ("POST", "/agents"),
            ("DELETE", f"/agents/{agent.id}"),
            ("POST", "/pipelines"),
            ("POST", "/pipeline-activations"),
            ("PUT", "/monitors/service-1/pipeline/layout"),
        ):
            status, body = await call(method, path, json={})
            assert (status, body["detail"]) == (
                403,
                "A key for an agent cannot do this. It needs a member.",
            ), path
        # Starting a service is allowed per key.
        status, body = await call("POST", "/pipelines/apply", json=start_request())
        assert status == 403 and "may not start" in body["detail"]
        # A key that starts in shadow only starts no service that raises alarms.
        status, _ = await call(
            "PATCH", f"/agents/{agent.id}", by_member, json={"starts": "shadow"}
        )
        assert status == 200
        status, body = await call("POST", "/pipelines/apply", json=start_request())
        assert status == 403 and "in shadow only" in body["detail"]
        assert reached == []
        status, body = await call(
            "POST", "/pipelines/apply", json=start_request(shadow=True)
        )
        assert (status, body["detail"]) == (422, "Reached the activation service")
        assert reached == [("Pump vibration", True)]
        status, _ = await call(
            "PATCH", f"/agents/{agent.id}", by_member, json={"starts": "live"}
        )
        assert status == 200
        status, body = await call("POST", "/pipelines/apply", json=start_request())
        assert (status, body["detail"]) == (422, "Reached the activation service")
        assert (
            await call(
                "PATCH", f"/agents/{agent.id}", by_member, json={"starts": "all"}
            )
        )[0] == 422
        # Taking a running service away stays with a member.
        status, body = await call(
            "POST",
            "/pipelines/apply",
            json=start_request(replace_service_id="service-1"),
        )
        assert status == 403 and "needs a member" in body["detail"]
        assert reached == [("Pump vibration", True), ("Pump vibration", False)]
        # A member has no agent's profile, and a revoked or made-up key is nobody.
        assert (await call("GET", "/agents/me", by_member))[0] == 403
        status, listed = await call("GET", "/agents", by_member)
        assert status == 200 and [item["name"] for item in listed] == ["Designer"]
        assert all("key" not in item and "key_hash" not in item for item in listed)
        assert (await call("DELETE", f"/agents/{agent.id}", by_member))[0] == 204
        assert (await call("GET", "/agents/me")) == (
            401,
            {"detail": "This key is not valid"},
        )
        made_up = {"Authorization": f"Bearer {new_agent_key()}"}
        assert (await call("GET", "/agents/me", made_up))[0] == 401


@pytest.mark.asyncio
async def test_a_member_creates_a_key_over_the_api_and_sees_it_once(keys):
    async with keys() as session:
        admin = await admin_of(session)
        token = access_token(admin)
    async with asgi_client(api(keys)) as client:
        headers = {"Authorization": f"Bearer {token}"}
        created = await client.post(
            "/v1/agents", headers=headers, json={"name": "Night shift"}
        )
        assert created.status_code == 201
        body = created.json()
        assert is_agent_key(body["key"]) and body["key"].endswith(body["key_hint"])
        assert (body["starts"], body["created_by"]) == ("nothing", "admin@example.com")
        again = await client.post(
            "/v1/agents", headers=headers, json={"name": "night shift"}
        )
        assert again.status_code == 409
        blank = await client.post("/v1/agents", headers=headers, json={"name": "  "})
        assert blank.status_code == 422
        # The new key works at once.
        me = await client.get(
            "/v1/agents/me", headers={"Authorization": f"Bearer {body['key']}"}
        )
        assert me.status_code == 200 and me.json()["id"] == body["id"]
