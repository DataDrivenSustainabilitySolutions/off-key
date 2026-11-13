"""Proposals: a design handed to a member to decide on, with the reason for it."""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI
from off_key_api_gateway.api.rate_limiter import limiter
from off_key_api_gateway.api.v1 import pipelines as gateway_pipelines
from off_key_core.db.base import get_db_async
from off_key_core.db.models import (
    Agent,
    DeploymentMaintenance,
    PipelineProposal,
    User,
)
from off_key_core.models.pipelines import pipeline_catalog, validate_pipeline
from off_key_core.schemas.agents import AgentCreate
from off_key_core.schemas.pipelines import (
    PipelineProposalCreate,
    PipelineProposalDecision,
)
from off_key_tactic_middleware.api.v1 import pipelines
from off_key_tactic_middleware.config.config import get_tactic_settings
from off_key_tactic_middleware.domain import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from off_key_tactic_middleware.services.accounts.agents import AgentService
from off_key_tactic_middleware.services.pipelines import proposals as proposal_service
from off_key_tactic_middleware.services.pipelines.proposals import PipelineProposals
from pydantic import ValidationError as SchemaError
from sqlalchemy import select

from tests.support.env import set_auth_env
from tests.support.gateway import gateway_app, member_profile
from tests.support.http import asgi_client
from tests.support.membership import bootstrap
from tests.support.tokens import access_token


def design() -> dict:
    return pipeline_catalog(True).templates[0].definition.model_dump(mode="json")


def proposal(**fields) -> PipelineProposalCreate:
    return PipelineProposalCreate.model_validate(
        {
            "name": "Pump vibration",
            "reason": "The bearing ran hot twice in October and nothing watched it.",
            "definition": design(),
            "bindings": {"value": "reading-1"},
        }
        | fields
    )


def test_a_proposal_names_the_monitor_and_says_why():
    made = proposal(name="  Pump vibration ", reason=" Because. ")
    assert (made.name, made.reason) == ("Pump vibration", "Because.")
    # The API names the monitor to replace as it names monitors elsewhere.
    replacing = proposal(replace_monitor_id="service-1")
    assert replacing.replace_service_id == "service-1"
    for missing in ({"name": " "}, {"reason": ""}, {"reason": "   "}):
        with pytest.raises(SchemaError):
            proposal(**missing)
    with pytest.raises(SchemaError):
        proposal(started=True)


@pytest_asyncio.fixture
async def library(member_database, monkeypatch):
    """The members' schema with agents, proposals and the release marker."""
    set_auth_env(monkeypatch)
    monkeypatch.setenv("TACTIC_PIPELINE_AUTHORING_ENABLED", "true")
    get_tactic_settings.cache_clear()
    engine, sessions = member_database
    async with engine.begin() as connection:
        for table in (Agent, PipelineProposal, DeploymentMaintenance):
            await connection.run_sync(table.__table__.create)
    await bootstrap(sessions)
    yield sessions
    get_tactic_settings.cache_clear()


async def admin_of(session) -> User:
    return await session.scalar(select(User).where(User.email == "admin@example.com"))


async def again_after_refusal(session, *callers) -> None:
    """End the refused request as the service does, and read its callers again."""
    await session.rollback()
    for caller in callers:
        await session.refresh(caller)


async def agent_named(session, name: str):
    agent, key = await AgentService(session).create(
        AgentCreate(name=name), await admin_of(session)
    )
    return agent, key


@pytest.mark.asyncio
async def test_an_agent_proposes_and_a_member_decides(library):
    async with library() as session:
        service = PipelineProposals(session)
        agent, _ = await agent_named(session, "Night shift agent")
        made = await service.create(
            proposal(test_run_id="run-7", replace_monitor_id="service-1"), agent
        )
        assert (made.author, made.author_kind, made.status) == (
            "Night shift agent",
            "agent",
            "open",
        )
        assert (made.test_run_id, made.replace_service_id) == ("run-7", "service-1")
        assert made.bindings == {"value": "reading-1"}
        # The design is kept whole, so it reads the same whatever changes later.
        assert (
            validate_pipeline(made.definition).fingerprint
            == validate_pipeline(proposal().definition).fingerprint
        )
        assert (await service.get(made.id)) == made
        second = await service.create(
            proposal(name="Fan current"), await admin_of(session)
        )
        assert (second.author, second.author_kind) == ("admin@example.com", "member")
        listed = await service.list()
        assert [item.name for item in listed.items] == ["Fan current", "Pump vibration"]
        assert not hasattr(listed.items[0], "definition")

        admin = await admin_of(session)
        declined = await service.decide(
            made.id,
            PipelineProposalDecision(
                status="declined", note=" Alarms too often at night. "
            ),
            admin,
        )
        assert (declined.status, declined.decided_by, declined.decision_note) == (
            "declined",
            "admin@example.com",
            "Alarms too often at night.",
        )
        assert declined.decided_at is not None
        # A proposal is decided once.
        for again in ("accepted", "declined"):
            with pytest.raises(ConflictError, match="already declined"):
                await service.decide(
                    made.id, PipelineProposalDecision(status=again), admin
                )
            await again_after_refusal(session, admin, agent)
        with pytest.raises(ConflictError, match="already declined"):
            await service.withdraw(made.id, agent)
        await session.rollback()
        assert [item.name for item in (await service.list("open")).items] == [
            "Fan current"
        ]
        assert [item.name for item in (await service.list("declined")).items] == [
            "Pump vibration"
        ]
        with pytest.raises(NotFoundError):
            await service.get("no-such-proposal")


@pytest.mark.asyncio
async def test_only_its_author_withdraws_a_proposal(library):
    async with library() as session:
        service = PipelineProposals(session)
        agent, _ = await agent_named(session, "Night shift agent")
        other, _ = await agent_named(session, "Auditor")
        made = await service.create(proposal(), agent)
        admin = await admin_of(session)
        for stranger in (other, admin):
            with pytest.raises(ForbiddenError, match="Only its author"):
                await service.withdraw(made.id, stranger)
            await again_after_refusal(session, agent, other, admin)
        withdrawn = await service.withdraw(made.id, agent)
        assert (withdrawn.status, withdrawn.decided_by) == ("withdrawn", None)
        own = await service.create(proposal(), admin)
        with pytest.raises(ForbiddenError):
            await service.withdraw(own.id, agent)
        await again_after_refusal(session, admin)
        assert (await service.withdraw(own.id, admin)).status == "withdrawn"


@pytest.mark.asyncio
async def test_a_proposal_is_refused_with_the_reason(library, monkeypatch):
    async with library() as session:
        service = PipelineProposals(session)
        agent, _ = await agent_named(session, "Night shift agent")
        broken = design()
        broken["edges"] = broken["edges"][:-1]
        with pytest.raises(ValidationError, match="without errors"):
            await service.create(proposal(definition=broken), agent)
        await again_after_refusal(session, agent)
        with pytest.raises(ValidationError, match="no input named phase_b"):
            await service.create(proposal(bindings={"phase_b": "reading-2"}), agent)
        await again_after_refusal(session, agent)
        # Readings can be left for the member to choose.
        assert (await service.create(proposal(bindings={}), agent)).bindings == {}
        monkeypatch.setattr(proposal_service, "MAX_OPEN_PROPOSALS", 2)
        await service.create(proposal(), agent)
        with pytest.raises(ConflictError, match="2 proposals wait for a decision"):
            await service.create(proposal(), agent)
        await again_after_refusal(session, agent)
        monkeypatch.setenv("TACTIC_PIPELINE_AUTHORING_ENABLED", "false")
        get_tactic_settings.cache_clear()
        with pytest.raises(ConflictError, match="authoring is disabled"):
            await service.create(proposal(), agent)


def tactic(sessions) -> FastAPI:
    async def session():
        async with sessions() as value:
            yield value
            await value.commit()

    app = FastAPI()
    business = APIRouter()
    business.include_router(pipelines.router, prefix="/api/v1")
    app.include_router(business)
    app.dependency_overrides[get_db_async] = session
    return app


@pytest.mark.asyncio
async def test_a_key_proposes_and_withdraws_but_does_not_decide(library):
    async with library() as session:
        _, key = await agent_named(session, "Night shift agent")
        token = access_token(await admin_of(session))
    by_key = {"Authorization": f"Bearer {key}"}
    by_member = {"Authorization": f"Bearer {token}"}
    body = proposal(replace_monitor_id="service-1").model_dump(mode="json")
    async with asgi_client(tactic(library)) as client:
        base = "/api/v1/monitors/pipeline-proposals"
        created = await client.post(base, headers=by_key, json=body)
        assert created.status_code == 201
        made = created.json()
        assert made["replace_monitor_id"] == "service-1"
        assert (made["author"], made["status"]) == ("Night shift agent", "open")
        listed = await client.get(base, headers=by_key, params={"status": "open"})
        assert [item["id"] for item in listed.json()["items"]] == [made["id"]]
        assert "definition" not in listed.json()["items"][0]
        decision = {"status": "accepted"}
        refused = await client.post(
            f"{base}/{made['id']}/decision", headers=by_key, json=decision
        )
        assert refused.status_code == 403
        assert "needs a member" in refused.json()["detail"]
        accepted = await client.post(
            f"{base}/{made['id']}/decision", headers=by_member, json=decision
        )
        assert accepted.status_code == 200
        assert accepted.json()["decided_by"] == "admin@example.com"
        late = await client.post(f"{base}/{made['id']}/withdraw", headers=by_key)
        assert (late.status_code, late.json()["detail"]) == (
            409,
            "This proposal is already accepted",
        )
        second = (await client.post(base, headers=by_key, json=body)).json()
        stranger = await client.post(
            f"{base}/{second['id']}/withdraw", headers=by_member
        )
        assert stranger.status_code == 403
        own = await client.post(f"{base}/{second['id']}/withdraw", headers=by_key)
        assert own.json()["status"] == "withdrawn"
        assert (await client.get(f"{base}/missing", headers=by_key)).status_code == 404
        wrong = await client.get(base, headers=by_key, params={"status": "started"})
        assert wrong.status_code == 422


@pytest.mark.asyncio
async def test_the_gateway_passes_proposals_on_under_their_public_names(monkeypatch):
    calls = []

    made = {
        "id": "proposal-1",
        "name": "Pump vibration",
        "reason": "The bearing ran hot twice in October.",
        "author": "admin@example.com",
        "author_kind": "member",
        "status": "open",
        "created_at": datetime.now(UTC).isoformat(),
        "definition": design(),
        "layout": {},
        "bindings": {},
        "test_run_id": None,
        "replace_service_id": "service-1",
        "decided_by": None,
        "decided_at": None,
        "decision_note": None,
    }

    async def request(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs.get("json_data"), kwargs.get("params")))
        return made if method == "POST" else {"items": []}

    monkeypatch.setattr(gateway_pipelines.tactic, "request", request)
    try:
        signed_in = {"Authorization": "Bearer member"}
        async with asgi_client(gateway_app(member_profile("admin"))) as client:
            client.headers.update(signed_in)
            listed = await client.get("/v1/pipeline-proposals?status=open")
            assert listed.json() == {"items": []}
            body = proposal().model_dump(mode="json") | {
                "replace_monitor_id": "service-1"
            }
            body.pop("replace_service_id")
            created = await client.post("/v1/pipeline-proposals", json=body)
            assert created.status_code == 201
            assert created.json()["replace_monitor_id"] == "service-1"
        async with asgi_client(gateway_app(member_profile())) as client:
            client.headers.update(signed_in)
            # A member who cannot manage monitors reads proposals and makes none.
            assert (await client.get("/v1/pipeline-proposals")).status_code == 200
            for path in ("", "/one/decision", "/one/withdraw"):
                refused = await client.post("/v1/pipeline-proposals" + path, json={})
                assert refused.status_code == 403, path
    finally:
        limiter.reset()
    assert calls[0] == (
        "GET",
        "/api/v1/monitors/pipeline-proposals",
        None,
        {"status": "open"},
    )
    method, endpoint, sent, _ = calls[1]
    assert (method, endpoint) == ("POST", "/api/v1/monitors/pipeline-proposals")
    assert (
        sent["replace_service_id"] == "service-1" and sent["name"] == "Pump vibration"
    )
    assert [call[:2] for call in calls[2:]] == [
        ("GET", "/api/v1/monitors/pipeline-proposals")
    ]
