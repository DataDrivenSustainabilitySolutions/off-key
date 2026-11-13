"""What the API lets an agent's key do."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from off_key_api_gateway import providers
from off_key_api_gateway.api import access
from off_key_api_gateway.api.rate_limiter import limiter
from off_key_core.auth.agents import new_agent_key
from off_key_core.models.pipelines import pipeline_catalog
from off_key_core.schemas.agents import AgentProfile
from off_key_core.schemas.pipelines import PipelineActivationView

from tests.support.gateway import (
    AGENT_KEY,
    BY_KEY,
    BY_MEMBER,
    Callers,
    agent,
    gateway_app,
    member,
    returning,
)
from tests.support.http import asgi_client

NEEDS_A_MEMBER = "A key for an agent cannot do this. It needs a member."


class Services:
    """Every provider replaced by a mock that records what it was asked."""

    def __init__(self):
        self.mocks = {
            provider: AsyncMock(name=provider.__name__)
            for provider in (
                providers.get_pipeline_activations,
                providers.get_agent_service,
                providers.get_member_service,
                providers.get_favorite_service,
                providers.get_system_service,
                providers.get_radar_orchestration_service,
                providers.get_pipeline_library,
                providers.get_pipeline_blocks,
                providers.get_alarm_service,
                providers.get_dojo_datasets,
                providers.get_dojo_labels,
                providers.get_dojo_runs,
            )
        }

    def overrides(self):
        return {provider: returning(mock) for provider, mock in self.mocks.items()}

    def of(self, provider):
        return self.mocks[provider]

    def asked(self):
        return [call for mock in self.mocks.values() for call in mock.mock_calls]


@pytest.fixture
def services():
    return Services()


@pytest.fixture
def gateway(services):
    yield gateway_app(overrides=services.overrides())
    limiter.reset()


def design() -> dict:
    return pipeline_catalog(True).templates[0].definition.model_dump(mode="json")


@pytest.mark.asyncio
async def test_a_key_reads_and_checks_a_design_as_itself(
    gateway, services, monkeypatch
):
    Callers(monkeypatch, agent=agent())
    async with asgi_client(gateway) as client:
        me = await client.get("/v1/agents/me", headers=BY_KEY)
        assert me.status_code == 200
        assert AgentProfile.model_validate(me.json()).name == "Designer"
        checked = await client.post(
            "/v1/pipelines/validate", headers=BY_KEY, json={"definition": design()}
        )
        assert checked.status_code == 200 and checked.json()["valid"]
    # Checking a design compiles it in process; nothing is stored.
    assert services.asked() == []


@pytest.mark.asyncio
async def test_a_key_is_refused_wherever_a_route_is_not_open_to_it(
    gateway, services, monkeypatch
):
    Callers(monkeypatch, agent=agent(starts="live"))
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
    assert services.asked() == []


@pytest.mark.asyncio
async def test_a_key_starts_a_service_only_when_it_may(gateway, services, monkeypatch):
    start = {
        "definition": design(),
        "bindings": {"value": "reading-1"},
        "display_name": "Pump vibration",
        "idempotency_key": "one",
    }
    key = agent()
    now = datetime.now(UTC).isoformat()
    activations = services.of(providers.get_pipeline_activations)
    activations.apply.return_value = PipelineActivationView.model_validate(
        {
            "id": "activation-1",
            "phase": "requested",
            "service_id": "service-1",
            "run_id": "run-1",
            "predecessor_service_id": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    Callers(monkeypatch, agent=key)
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
        assert services.asked() == []
        # The grant is read with every request, so it holds from the next one.
        key.starts = "live"
        started = await client.post("/v1/pipelines/apply", headers=BY_KEY, json=start)
        assert started.status_code == 202
        assert started.json()["monitor_id"] == "service-1"
        # A key that starts in shadow only is refused a live start and may
        # start in shadow.
        key.starts = "shadow"
        live = await client.post("/v1/pipelines/apply", headers=BY_KEY, json=start)
        assert live.status_code == 403
        shadowed = await client.post(
            "/v1/pipelines/apply", headers=BY_KEY, json=start | {"shadow": True}
        )
        assert shadowed.status_code == 202
    applied = activations.apply.await_args_list
    assert [call.args[0].shadow for call in applied] == [False, True]


@pytest.mark.asyncio
async def test_a_revoked_or_unknown_key_is_nobody(gateway, services, monkeypatch):
    Callers(monkeypatch, agent=agent())
    other = {"Authorization": f"Bearer {new_agent_key()}"}
    async with asgi_client(gateway) as client:
        for path in ("/agents/me", "/devices", "/pipelines"):
            response = await client.get("/v1" + path, headers=other)
            assert response.status_code == 401
    assert services.asked() == []


@pytest.mark.asyncio
async def test_members_manage_keys_and_have_no_agent_profile(
    gateway, services, monkeypatch
):
    keys = services.of(providers.get_agent_service)
    keys.create.return_value = (agent(), AGENT_KEY)
    Callers(monkeypatch, agent=agent(), member=member("admin"))
    async with asgi_client(gateway) as client:
        response = await client.post(
            "/v1/agents", headers=BY_MEMBER, json={"name": "Designer"}
        )
        assert response.status_code == 201 and response.json()["key"] == AGENT_KEY
        mine = await client.get("/v1/agents/me", headers=BY_MEMBER)
        assert mine.status_code == 403
    assert keys.create.await_args.args[0].name == "Designer"
    assert [call[0] for call in services.asked()] == ["create"]

    keys.reset_mock()
    Callers(monkeypatch, agent=agent(), member=member())
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
    assert keys.mock_calls == []


def test_an_agent_never_shares_a_members_rate_limit():
    assert access.caller_key(member(id=4)) == "4"
    assert access.caller_key(agent()) == "agent-4"
