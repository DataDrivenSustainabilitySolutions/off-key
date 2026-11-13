"""The gateway as an MCP server: what an agent's key finds at `/v1/mcp`."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from off_key_api_gateway.api import mcp_tools
from off_key_api_gateway.api.rate_limiter import limiter
from off_key_api_gateway.app import build_app
from off_key_api_gateway.facades.tactic import TacticError
from off_key_api_gateway.settings import AppSettings
from off_key_core.auth.agents import new_agent_key
from off_key_core.models.pipelines import pipeline_catalog
from off_key_core.schemas.pipeline_tools import ComponentSearchQuery, DesignEditRequest
from off_key_core.schemas.pipelines import PipelineValidateRequest
from off_key_tactic_middleware.api.v1 import pipelines as tactic_pipelines

from tests.support.gateway import (
    BY_KEY,
    BY_MEMBER,
    Asked,
    StandInTactic,
    agent_profile,
    member_profile,
)

URL = "http://gateway/v1/mcp"
MONITORS = "/api/v1/monitors"
DOJO = "/api/v1/dojo"
THEN = datetime(2026, 3, 1, tzinfo=UTC).isoformat()
WITHOUT_THE_GRANT = [
    "list_devices",
    "list_readings",
    "profile_reading",
    "search_components",
    "get_component",
    "list_designs",
    "get_design",
    "edit_design",
    "validate_design",
    "test_design",
    "get_test",
    "propose_design",
    "list_proposals",
    "withdraw_proposal",
]


@pytest.fixture
def gateway():
    limiter.reset()
    yield build_app(AppSettings(APP_NAME="off-key-test"))
    limiter.reset()


@pytest.fixture
def no_pause(monkeypatch):
    """A tool that waits for something to finish asks again at once."""
    monkeypatch.setattr(mcp_tools, "PAUSE", 0.0)


async def designs(asked: Asked):
    """TACTIC's own answers where they need no database."""
    path = asked.endpoint.removeprefix(f"{MONITORS}/pipelines")
    if path == "/catalog":
        return pipeline_catalog(True)
    if path == "/catalog/search":
        query = ComponentSearchQuery.model_validate(asked.params or {})
        return await tactic_pipelines.search_catalog(query)
    if path.startswith("/catalog/components/"):
        return await tactic_pipelines.catalog_component(unquote(path.rsplit("/")[-1]))
    if path == "/edit":
        change = DesignEditRequest.model_validate(asked.body)
        return await tactic_pipelines.edit_unsaved_design(change)
    if path == "/validate":
        check = PipelineValidateRequest.model_validate(asked.body)
        return await tactic_pipelines.validate_unsaved_design(check)
    raise TacticError("Not found", status=404)


def tactic(monkeypatch, answers=None, **profile) -> StandInTactic:
    return StandInTactic(
        monkeypatch, agent_profile(**profile), answers=answers, otherwise=designs
    )


@asynccontextmanager
async def running(app, headers=None):
    """The gateway as it runs, behind a client that sends ``headers``."""
    client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), headers=headers
    )
    async with app.router.lifespan_context(app), client:
        yield client


@asynccontextmanager
async def connected(app):
    """An MCP session with the gateway, as the client of an agent holds it."""
    async with (
        running(app, BY_KEY) as http,
        Client(streamable_http_client(URL, http_client=http)) as client,
    ):
        yield client


def said(result):
    """What a tool answered: its JSON, or the words of a refusal."""
    [content] = result.content
    return content.text if result.is_error else json.loads(content.text)


def starter(name: str = "adaptive_stream") -> dict:
    found = next(item for item in pipeline_catalog(True).templates if item.id == name)
    return found.model_dump(mode="json")


def proposal(**fields) -> dict:
    return {
        "id": "p1",
        "name": "Pump vibration",
        "reason": "Catches the bearing fault of March with one alarm a week.",
        "author": "Designer",
        "author_kind": "agent",
        "status": "open",
        "test_run_id": "run-1",
        "replace_service_id": None,
        "decided_by": None,
        "decided_at": None,
        "decision_note": None,
        "created_at": THEN,
        "definition": starter()["definition"],
        "layout": starter()["layout"],
        "bindings": {"value": "r-power"},
    } | fields


@pytest.mark.asyncio
async def test_an_agent_finds_the_tools_its_key_allows(gateway, monkeypatch):
    stand_in = tactic(monkeypatch)
    async with connected(gateway) as client:
        assert client.server_info.name == "off-key"
        assert client.instructions == mcp_tools.INSTRUCTIONS
        tools = (await client.list_tools()).tools
        # The grant is read with every request, so it holds from the next one.
        stand_in.profile["may_start"] = True
        granted = (await client.list_tools()).tools

    assert [tool.name for tool in tools] == WITHOUT_THE_GRANT
    assert [tool.name for tool in granted] == [
        *WITHOUT_THE_GRANT,
        "start_monitor",
        "get_start",
    ]
    for tool in granted:
        assert tool.description == " ".join(tool.description.split()) != "", tool.name
        assert tool.input_schema["type"] == "object", tool.name
        # A name the tool does not know is refused, and the schema says so.
        assert tool.input_schema["additionalProperties"] is False, tool.name
    # A client may ask before it lets a tool change something others see.
    assert {tool.name for tool in granted if not tool.annotations.read_only_hint} == {
        "test_design",
        "propose_design",
        "withdraw_proposal",
        "start_monitor",
    }
    # An agent reads the whole list with every session, so it stays short.
    listing = [tool.model_dump(mode="json", exclude_none=True) for tool in granted]
    assert len(json.dumps(listing)) < 24_000


def test_a_schema_says_nothing_twice():
    schema = {
        "title": "Note",
        "type": "object",
        "properties": {"title": {"title": "Title", "type": "string"}},
        "$defs": {"title": {"title": "Title", "enum": ["a"]}},
        "anyOf": [{"title": "One", "type": "null"}],
    }
    assert mcp_tools._without_titles(schema) == {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "$defs": {"title": {"enum": ["a"]}},
        "anyOf": [{"type": "null"}],
    }


@pytest.mark.asyncio
async def test_only_the_key_of_an_agent_opens_the_door(gateway, monkeypatch):
    stand_in = StandInTactic(monkeypatch, agent_profile(), member=member_profile())
    ask = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    accepts = {"Accept": "application/json, text/event-stream"}
    async with running(gateway) as client:
        nobody = await client.post(URL, json=ask, headers=accepts)
        assert nobody.status_code == 401
        assert nobody.headers["www-authenticate"] == "Bearer"
        assert nobody.json() == {"detail": "Sign in to continue"}

        other = {"Authorization": f"Bearer {new_agent_key()}"}
        revoked = await client.post(URL, json=ask, headers=accepts | other)
        assert revoked.status_code == 401
        assert revoked.json() == {"detail": "This key is not valid"}

        member = await client.post(URL, json=ask, headers=accepts | BY_MEMBER)
        assert member.status_code == 403
        assert member.json() == {"detail": "Only a key for an agent can ask this"}

        # Nothing is streamed, so there is nothing to listen to.
        listening = await client.get(URL, headers=accepts | BY_KEY)
        assert listening.status_code == 405
        assert listening.headers["allow"] == "POST"

        agent = await client.post(URL, json=ask, headers=accepts | BY_KEY)
        assert agent.status_code == 200
        assert agent.headers["content-type"].startswith("application/json")
        assert len(agent.json()["result"]["tools"]) == len(WITHOUT_THE_GRANT)
    assert stand_in.forwarded() == []


@pytest.mark.asyncio
async def test_a_tool_is_a_call_to_the_api_as_the_agent(gateway, monkeypatch):
    device = {
        "id": "pump",
        "label": "Pump",
        "kind": "device",
        "broker_id": "plant",
        "parent_id": None,
        "reading_ids": ["r-power"],
        "online": True,
        "last_seen": THEN,
    }
    profile = {
        "reading_id": "r-power",
        "start": THEN,
        "end": THEN,
        "bucket_seconds": 60.0,
    }
    stand_in = tactic(
        monkeypatch,
        answers={
            ("GET", "/api/v1/data/devices"): [device],
            ("GET", "/api/v1/data/devices/pump/readings"): [],
            ("GET", "/api/v1/data/readings/r-power/profile"): profile,
        },
    )
    async with connected(gateway) as client:
        devices = said(await client.call_tool("list_devices", {"active": True}))
        assert [item["id"] for item in devices] == ["pump"]
        assert (
            said(await client.call_tool("list_readings", {"device_id": "pump"})) == []
        )
        looked = said(
            await client.call_tool("profile_reading", {"reading_id": "r-power"})
        )
        assert looked["bucket_seconds"] == 60

        found = said(
            await client.call_tool(
                "search_components",
                {"query": "calm noise", "group": "prepare", "limit": 3},
            )
        )
        assert found["components"][0]["id"] == "prepare.smooth"
        step = said(
            await client.call_tool("get_component", {"component_id": "prepare.smooth"})
        )
        assert "window_size" in step["parameter_schema"]["properties"]

        start = said(
            await client.call_tool(
                "get_design", {"source": "starter", "id": "adaptive_stream"}
            )
        )
        edited = said(
            await client.call_tool(
                "edit_design",
                {
                    "definition": start["definition"],
                    "layout": start["layout"],
                    "edits": [
                        {
                            "op": "add_step",
                            "component": "prepare.smooth",
                            "after": "input",
                            "before": "detector",
                        },
                        {"op": "set_label", "id": "prepare_smooth_1", "label": "Calm"},
                        {"op": "set_label", "id": "input", "label": "Power"},
                        # Null takes a title away; it is not an edit left out.
                        {"op": "set_label", "id": "input", "label": None},
                    ],
                },
            )
        )
        assert edited["added"] == ["prepare_smooth_1"]
        assert edited["report"]["valid"] and edited["report"]["issues"] == []
        labels = {
            node["id"]: node.get("label") for node in edited["definition"]["nodes"]
        }
        assert (labels["prepare_smooth_1"], labels["input"]) == ("Calm", None)
        # A design passes from tool to tool as it was answered.
        checked = said(
            await client.call_tool(
                "validate_design", {"definition": edited["definition"]}
            )
        )
        assert checked["valid"]

    assert [asked[:2] for asked in stand_in.forwarded()] == [
        ("GET", "/api/v1/data/devices"),
        ("GET", "/api/v1/data/devices/pump/readings"),
        ("GET", "/api/v1/data/readings/r-power/profile"),
        ("GET", f"{MONITORS}/pipelines/catalog/search"),
        ("GET", f"{MONITORS}/pipelines/catalog/components/prepare.smooth"),
        ("GET", f"{MONITORS}/pipelines/catalog"),
        ("POST", f"{MONITORS}/pipelines/edit"),
        ("POST", f"{MONITORS}/pipelines/validate"),
    ]
    assert stand_in.last("GET", "/api/v1/data/devices").params == {"active": True}
    assert stand_in.last("GET", "/api/v1/data/readings/r-power/profile").params == {
        "days": 14
    }
    # TACTIC is asked with the key itself, so it checks the key again.
    assert all(
        asked.headers == BY_KEY
        for asked in stand_in.forwarded()
        if asked.endpoint.startswith(MONITORS)
    )


@pytest.mark.asyncio
async def test_a_refusal_reaches_the_agent_in_the_words_of_the_api(
    gateway, monkeypatch
):
    stand_in = tactic(monkeypatch)
    design = starter()["definition"]
    start = {"name": "Pump", "definition": design, "bindings": {"value": "r-power"}}
    refusals = (
        # The tool refuses what it does not know, without a call.
        ("drop_database", {}, "There is no tool called drop_database"),
        ("start_monitor", start, "There is no tool called start_monitor"),
        (
            "search_components",
            {"query": "calm", "nope": 3},
            "nope: Extra inputs are not permitted",
        ),
        (
            "profile_reading",
            {"reading_id": "r-power", "days": 400},
            "days: Input should be less than or equal to 90",
        ),
        ("get_component", {"component_id": "a/b"}, "'a/b' is not an id"),
        # The route refuses, and says what to change.
        (
            "get_component",
            {"component_id": "prepare.none"},
            "Pipeline component not found",
        ),
        (
            "get_design",
            {"source": "starter", "id": "none"},
            "No starter is called 'none'",
        ),
        (
            "edit_design",
            {"definition": design, "edits": [{"op": "remove_step", "id": "gone"}]},
            "Edit 1 (remove_step): The design has no step 'gone'",
        ),
        (
            "validate_design",
            {"definition": {"nodes": 3}},
            "definition.nodes: Input should be a valid list",
        ),
    )
    async with connected(gateway) as client:
        for name, arguments, words in refusals:
            result = await client.call_tool(name, arguments)
            assert result.is_error, name
            assert words in said(result), name
    assert [asked.endpoint for asked in stand_in.forwarded()] == [
        f"{MONITORS}/pipelines/catalog/components/prepare.none",
        f"{MONITORS}/pipelines/catalog",
        f"{MONITORS}/pipelines/edit",
    ]


@pytest.mark.asyncio
async def test_a_design_is_tested_on_history(gateway, monkeypatch, no_pause):
    dataset = {
        "id": "d1",
        "name": "Test by an agent · last 3 days",
        "description": "",
        "origin": "history",
        "point_count": 100,
        "series_count": 1,
        "start_at": THEN,
        "end_at": THEN,
        "created_by": None,
        "created_at": THEN,
        "source": {},
        "series": [
            {
                "id": "s1",
                "position": 0,
                "name": "Power",
                "unit": "kW",
                "reading_id": "r-power",
                "point_count": 100,
                "start_at": THEN,
                "end_at": THEN,
            }
        ],
    }
    run = {
        "id": "run-1",
        "dataset_id": "d1",
        "name": "Test by an agent",
        "status": "queued",
        "strategy": "adaptive_stream",
        "points_total": 100,
        "points_read": 0,
        "result_count": 0,
        "alarm_count": 0,
        "error": None,
        "created_by": None,
        "created_at": THEN,
        "started_at": None,
        "finished_at": None,
        "definition": {"compiled": "long"},
        "bindings": [{"slot_id": "value", "series_id": "s1", "series_name": "Power"}],
        "alignment": {},
        "cancel_requested": False,
        "stats": {"waiting_for_all": 2},
    }
    metrics = {
        "run_id": "run-1",
        "run_name": "Test by an agent",
        "strategy": "adaptive_stream",
        "scored_from": THEN,
        "scored_to": THEN,
        "labels_total": 0,
        "labels_scored": 0,
        "labels_detected": 0,
        "detection_rate": None,
        "median_delay_seconds": None,
        "max_delay_seconds": None,
        "alarm_count": 7,
        "false_alarms": 2,
        "evaluated_seconds": 86400.0,
        "false_alarms_per_day": 2.0,
        "labels": [],
    }
    states = iter(
        [run | {"status": "running"}, run | {"status": "succeeded", "alarm_count": 7}]
    )
    stand_in = tactic(
        monkeypatch,
        answers={
            ("POST", f"{DOJO}/datasets/history"): dataset,
            ("GET", f"{DOJO}/datasets/d1"): dataset,
            ("POST", f"{DOJO}/runs"): run,
            ("GET", f"{DOJO}/runs/run-1"): lambda asked: next(states),
            ("GET", f"{DOJO}/runs/run-1/metrics"): metrics,
        },
    )
    test = {"definition": starter()["definition"], "bindings": {"value": "r-power"}}
    async with connected(gateway) as client:
        queued = said(await client.call_tool("test_design", test | {"days": 3}))
        assert queued.keys() == {
            "run_id",
            "dataset_id",
            "status",
            "points_total",
            "start_at",
            "end_at",
        }
        assert (queued["run_id"], queued["dataset_id"]) == ("run-1", "d1")
        # The values of the readings are copied, and each input takes its own.
        copied = stand_in.last("POST", f"{DOJO}/datasets/history").body
        assert copied["name"] == "Test by an agent · last 3 days"
        assert copied["reading_ids"] == ["r-power"]
        window = datetime.fromisoformat(copied["end"]) - datetime.fromisoformat(
            copied["start"]
        )
        assert window == timedelta(days=3)
        queue = stand_in.last("POST", f"{DOJO}/runs").body
        assert (queue["dataset_id"], queue["bindings"]) == ("d1", {"value": "s1"})

        # A changed design runs on the same copy, so the two results compare.
        await client.call_tool("test_design", test | {"dataset_id": "d1"})
        elsewhere = await client.call_tool(
            "test_design",
            {**test, "bindings": {"value": "r-flow"}, "dataset_id": "d1"},
        )
        assert said(elsewhere) == "The dataset holds no values of r-flow"
        asked = [asked.endpoint for asked in stand_in.forwarded()]
        assert asked.count(f"{DOJO}/datasets/history") == 1
        assert asked.count(f"{DOJO}/runs") == 2

        # It waits for the run to finish, and spares the agent the compiled design.
        result = said(await client.call_tool("get_test", {"run_id": "run-1"}))
        assert (result["status"], result["alarm_count"]) == ("succeeded", 7)
        assert result["stats"] == {"waiting_for_all": 2}
        assert "definition" not in result
        assert result["metrics"]["false_alarms_per_day"] == 2
    assert all(asked.headers == BY_KEY for asked in stand_in.forwarded())


@pytest.mark.asyncio
async def test_a_design_is_proposed_and_started_only_with_the_grant(
    gateway, monkeypatch, no_pause
):
    activation = {
        "id": "activation-1",
        "phase": "requested",
        "service_id": "service-1",
        "run_id": "run-1",
        "predecessor_service_id": None,
        "error": None,
        "created_at": THEN,
        "updated_at": THEN,
    }
    phases = iter(
        [activation | {"phase": "starting"}, activation | {"phase": "succeeded"}]
    )
    summary = {
        key: value
        for key, value in proposal().items()
        if key not in {"definition", "layout", "bindings"}
    }
    stand_in = tactic(
        monkeypatch,
        answers={
            ("POST", f"{MONITORS}/pipeline-proposals"): proposal(
                replace_service_id="service-9"
            ),
            ("GET", f"{MONITORS}/pipeline-proposals"): {"items": [summary]},
            ("POST", f"{MONITORS}/pipeline-proposals/p1/withdraw"): proposal(
                status="withdrawn"
            ),
            ("POST", f"{MONITORS}/pipelines/apply"): activation,
            ("GET", f"{MONITORS}/pipeline-activations/activation-1"): (
                lambda asked: next(phases)
            ),
        },
    )
    design = starter()
    start = {
        "name": "Pump vibration",
        "definition": design["definition"],
        "layout": design["layout"],
        "bindings": {"value": "r-power"},
    }
    async with connected(gateway) as client:
        proposed = said(
            await client.call_tool(
                "propose_design",
                start
                | {
                    "reason": "Catches the bearing fault of March.",
                    "test_run_id": "run-1",
                    "replace_monitor_id": "service-9",
                },
            )
        )
        assert (proposed["id"], proposed["replace_monitor_id"]) == ("p1", "service-9")
        handed = stand_in.last("POST", f"{MONITORS}/pipeline-proposals").body
        assert handed["name"] == "Pump vibration"
        assert handed["bindings"] == {"value": "r-power"}
        assert handed["layout"] == design["layout"]
        assert (handed["test_run_id"], handed["replace_service_id"]) == (
            "run-1",
            "service-9",
        )

        waiting = said(await client.call_tool("list_proposals", {"status": "open"}))
        assert [item["id"] for item in waiting["items"]] == ["p1"]
        assert stand_in.last("GET", f"{MONITORS}/pipeline-proposals").params == {
            "status": "open"
        }
        taken_back = said(
            await client.call_tool("withdraw_proposal", {"proposal_id": "p1"})
        )
        assert taken_back["status"] == "withdrawn"

        refused = await client.call_tool("start_monitor", start)
        assert said(refused) == "There is no tool called start_monitor"
        assert not any(
            asked.endpoint.endswith("/apply") for asked in stand_in.forwarded()
        )

        stand_in.profile["may_start"] = True
        started = said(await client.call_tool("start_monitor", start))
        assert (started["id"], started["monitor_id"]) == ("activation-1", "service-1")
        applied = stand_in.last("POST", f"{MONITORS}/pipelines/apply").body
        assert applied["display_name"] == "Pump vibration"
        assert applied["bindings"] == {"value": "r-power"}
        assert applied["replace_service_id"] is None
        # A start is named even where the agent names none, and by the agent's
        # own word where it repeats a call.
        assert len(applied["idempotency_key"]) == 32
        await client.call_tool("start_monitor", start | {"idempotency_key": "again"})
        again = stand_in.last("POST", f"{MONITORS}/pipelines/apply").body
        assert again["idempotency_key"] == "again"

        settled = said(
            await client.call_tool("get_start", {"activation_id": "activation-1"})
        )
        assert (settled["phase"], settled["monitor_id"]) == ("succeeded", "service-1")


@pytest.mark.asyncio
async def test_a_design_is_read_from_where_it_is(gateway, monkeypatch):
    design = starter("static_baseline")
    saved = {
        "id": "pl-1",
        "name": "Pumps",
        "description": "For every pump of the plant.",
        "archived": False,
        "version": 3,
        "draft": design["definition"],
        "layout": design["layout"],
        "created_at": THEN,
        "updated_at": THEN,
    }
    listed = {
        key: saved[key] for key in ("id", "name", "description", "archived", "version")
    } | {"revision_count": 1, "created_at": THEN, "updated_at": THEN}
    service = {
        "id": "service-1",
        "display_name": "Pump vibration",
        "stream_ids": ["r-power"],
        "status": True,
        "container_name": "radar-service-1",
    }
    reading = {
        "slot_id": "value",
        "reading_id": "r-power",
        "label": "Power",
        "unit": "kW",
        "device_id": "pump",
        "entity_label": "Pump",
        "source_id": "plant",
        "source_label": "Plant",
        "collection_policy": {},
    }
    runs = {
        "run": {
            "id": "run-7",
            "service_id": "service-1",
            "revision_id": "rev-2",
            "predecessor_run_id": None,
            "status": "running",
            "created_at": THEN,
            "ended_at": None,
            "execution": None,
            "binding_metadata": {
                "system_revision": 4,
                "collection_revision": 9,
                "readings": [reading],
            },
        },
        "history": [],
        "definition": design["definition"],
        "layout": design["layout"],
    }
    stand_in = tactic(
        monkeypatch,
        answers={
            ("GET", f"{MONITORS}/pipelines"): {"items": [listed]},
            ("GET", "/api/v1/orchestration/radar/services/"): [service],
            ("GET", f"{MONITORS}/pipelines/pl-1"): saved,
            ("GET", f"{MONITORS}/pipeline-proposals/p1"): proposal(),
            ("GET", f"{MONITORS}/service-1/pipeline"): runs,
        },
    )
    async with connected(gateway) as client:
        assert said(await client.call_tool("list_designs", {})) == {
            "starters": [
                {"id": item.id, "name": item.name}
                for item in pipeline_catalog(True).templates
            ],
            "templates": [
                {
                    "id": "pl-1",
                    "name": "Pumps",
                    "description": "For every pump of the plant.",
                }
            ],
            "monitors": [
                {
                    "id": "service-1",
                    "display_name": "Pump vibration",
                    "reading_ids": ["r-power"],
                    "active": True,
                }
            ],
        }
        assert stand_in.last("GET", f"{MONITORS}/pipelines").params["limit"] == 100

        async def read(source: str, key: str) -> dict:
            return said(
                await client.call_tool("get_design", {"source": source, "id": key})
            )

        template = await read("template", "pl-1")
        assert template.keys() == {"name", "description", "definition", "layout"}
        proposed = await read("proposal", "p1")
        assert proposed["bindings"] == {"value": "r-power"}
        monitored = await read("monitor", "service-1")
        assert monitored.keys() == {"definition", "layout", "bindings"}
        assert monitored["bindings"] == {"value": "r-power"}
        # Each is the design itself, in the form the other tools take.
        for held in (template, proposed, monitored):
            checked = await client.call_tool(
                "validate_design", {"definition": held["definition"]}
            )
            assert said(checked)["valid"]
