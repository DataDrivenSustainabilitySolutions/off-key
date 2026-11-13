"""What the public gateway lets an agent's key do."""

from datetime import UTC, datetime

import pytest
from off_key_api_gateway.api import access
from off_key_api_gateway.api.rate_limiter import limiter
from off_key_core.auth.agents import new_agent_key
from off_key_core.models.pipelines import pipeline_catalog
from off_key_core.schemas.agents import AgentProfile

from tests.support.gateway import (
    AGENT_KEY,
    BY_KEY,
    BY_MEMBER,
    StandInTactic,
    agent_profile,
    gateway_app,
    member_profile,
)
from tests.support.http import asgi_client

NEEDS_A_MEMBER = "A key for an agent cannot do this. It needs a member."


@pytest.fixture
def gateway():
    yield gateway_app()
    limiter.reset()


def design() -> dict:
    return pipeline_catalog(True).templates[0].definition.model_dump(mode="json")


@pytest.mark.asyncio
async def test_a_key_reads_and_checks_a_design_as_itself(gateway, monkeypatch):
    report = {"valid": True, "issues": [], "definition": None}
    tactic = StandInTactic(
        monkeypatch,
        agent_profile(),
        answers={("POST", "/api/v1/monitors/pipelines/validate"): report},
    )
    async with asgi_client(gateway) as client:
        me = await client.get("/v1/agents/me", headers=BY_KEY)
        assert me.status_code == 200
        assert AgentProfile.model_validate(me.json()).name == "Designer"
        checked = await client.post(
            "/v1/pipelines/validate", headers=BY_KEY, json={"definition": design()}
        )
        assert checked.status_code == 200 and checked.json()["valid"]
    # TACTIC is asked with the key itself, so it checks the key again.
    assert [asked[:3] for asked in tactic.forwarded()] == [
        ("POST", "/api/v1/monitors/pipelines/validate", BY_KEY)
    ]


@pytest.mark.asyncio
async def test_a_key_is_refused_wherever_a_route_is_not_open_to_it(
    gateway, monkeypatch
):
    tactic = StandInTactic(monkeypatch, agent_profile(starts="live"))
    closed = (
        ("GET", "/me"),
        ("GET", "/favorites"),
        ("POST", "/favorites"),
        ("GET", "/catalogue"),
        ("PUT", "/catalogue"),
        ("PUT", "/recording"),
        ("GET", "/storage"),
        ("POST", "/live/views"),
        ("POST", "/monitors"),
        ("PATCH", "/monitors/example"),
        ("POST", "/monitors/example/stop"),
        ("DELETE", "/monitors/example"),
        ("PUT", "/monitors/example/pipeline/layout"),
        ("POST", "/pipelines"),
        ("PATCH", "/pipelines/example"),
        ("PUT", "/pipelines/example/draft"),
        ("POST", "/pipelines/example/revisions"),
        ("POST", "/pipeline-activations"),
        ("POST", "/pipeline-blocks"),
        ("DELETE", "/pipeline-blocks/example"),
        ("POST", "/forecast-models/downloads"),
        ("POST", "/alarms"),
        ("DELETE", "/alarms/example"),
        ("POST", "/dojo/datasets/csv"),
        ("PATCH", "/dojo/datasets/example"),
        ("DELETE", "/dojo/datasets/example"),
        ("POST", "/dojo/datasets/example/labels"),
        ("POST", "/dojo/runs/example/cancel"),
        ("POST", "/dojo/runs/example/promote"),
        ("DELETE", "/dojo/runs/example"),
        ("GET", "/members"),
        ("POST", "/invitations"),
        ("PATCH", "/members/19"),
        ("GET", "/roles"),
        ("POST", "/roles"),
        ("GET", "/agents"),
        ("POST", "/agents"),
        ("PATCH", "/agents/4"),
        ("DELETE", "/agents/4"),
    )
    async with asgi_client(gateway) as client:
        for method, path in closed:
            response = await client.request(
                method, "/v1" + path, headers=BY_KEY, json={}
            )
            assert (response.status_code, response.json()["detail"]) == (
                403,
                NEEDS_A_MEMBER,
            ), f"{method} {path}"
    assert tactic.forwarded() == []


@pytest.mark.asyncio
async def test_a_key_starts_a_service_only_when_it_may(gateway, monkeypatch):
    start = {
        "definition": design(),
        "bindings": {"value": "reading-1"},
        "display_name": "Pump vibration",
        "idempotency_key": "one",
    }
    profile = agent_profile()
    now = datetime.now(UTC).isoformat()
    activation = {
        "id": "activation-1",
        "phase": "requested",
        "service_id": "service-1",
        "run_id": "run-1",
        "predecessor_service_id": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    tactic = StandInTactic(
        monkeypatch,
        profile,
        answers={("POST", "/api/v1/monitors/pipelines/apply"): activation},
    )
    async with asgi_client(gateway) as client:
        for method, path in (
            ("POST", "/pipelines/apply"),
            ("POST", "/pipeline-activations/example/cancel"),
        ):
            refused = await client.request(
                method, "/v1" + path, headers=BY_KEY, json=start
            )
            assert refused.status_code == 403
            assert "may not start" in refused.json()["detail"]
        assert tactic.forwarded() == []
        # The grant is read with every request, so it holds from the next one.
        profile["starts"] = "live"
        started = await client.post("/v1/pipelines/apply", headers=BY_KEY, json=start)
        assert started.status_code == 202
        assert started.json()["monitor_id"] == "service-1"
        # A key that starts in shadow only reaches TACTIC, which reads the
        # request and decides.
        profile["starts"] = "shadow"
        shadowed = await client.post(
            "/v1/pipelines/apply", headers=BY_KEY, json=start | {"shadow": True}
        )
        assert shadowed.status_code == 202
    applied = tactic.forwarded()
    assert [asked[:2] for asked in applied] == [
        ("POST", "/api/v1/monitors/pipelines/apply")
    ] * 2
    assert [asked.body["shadow"] for asked in applied] == [False, True]


@pytest.mark.asyncio
async def test_a_revoked_or_unknown_key_is_nobody(gateway, monkeypatch):
    tactic = StandInTactic(monkeypatch, agent_profile())
    other = {"Authorization": f"Bearer {new_agent_key()}"}
    async with asgi_client(gateway) as client:
        for path in ("/agents/me", "/devices", "/pipelines"):
            response = await client.get("/v1" + path, headers=other)
            assert response.status_code == 401
    assert tactic.forwarded() == []


@pytest.mark.asyncio
async def test_members_manage_keys_and_have_no_agent_profile(gateway, monkeypatch):
    admin = member_profile("admin")
    created = agent_profile() | {"key": AGENT_KEY}
    tactic = StandInTactic(
        monkeypatch,
        agent_profile(),
        member=admin,
        answers={("POST", "/api/v1/agents"): created},
    )
    async with asgi_client(gateway) as client:
        response = await client.post(
            "/v1/agents", headers=BY_MEMBER, json={"name": "Designer"}
        )
        assert response.status_code == 201 and response.json()["key"] == AGENT_KEY
        mine = await client.get("/v1/agents/me", headers=BY_MEMBER)
        assert mine.status_code == 403
    assert [asked[:3] for asked in tactic.forwarded()] == [
        ("POST", "/api/v1/agents", BY_MEMBER)
    ]

    plain = member_profile()
    tactic = StandInTactic(monkeypatch, agent_profile(), member=plain)
    async with asgi_client(gateway) as client:
        for method, path in (
            ("GET", "/agents"),
            ("POST", "/agents"),
            ("PATCH", "/agents/4"),
            ("DELETE", "/agents/4"),
        ):
            response = await client.request(
                method, "/v1" + path, headers=BY_MEMBER, json={"name": "x"}
            )
            assert response.status_code == 403, path
    assert tactic.forwarded() == []


def test_an_agent_never_shares_a_members_rate_limit():
    member = member_profile(id=4)
    assert access.caller_key(member) == "4"
    assert access.caller_key(AgentProfile.model_validate(agent_profile())) == "agent-4"
