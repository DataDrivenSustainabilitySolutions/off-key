"""The API as an MCP server: what an agent's key finds at `/v1/mcp`."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from off_key_api_gateway import providers
from off_key_api_gateway.api import mcp_tools
from off_key_api_gateway.api.rate_limiter import limiter
from off_key_api_gateway.app import build_app
from off_key_api_gateway.settings import AppSettings
from off_key_core.auth.agents import new_agent_key
from off_key_core.db.base import get_db_async
from off_key_core.db.models import Agent
from off_key_core.models.pipelines import pipeline_catalog

from tests.support.gateway import BY_KEY, BY_MEMBER, Callers, agent, member, returning

URL = "http://gateway/v1/mcp"
THEN = datetime(2026, 3, 1, tzinfo=UTC).isoformat()
WITHOUT_THE_GRANT = [
    "get_access",
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


class Stores:
    """What the routes behind the tools read and change, each a mock that
    records what it was asked."""

    def __init__(self):
        self.data = AsyncMock()
        self.data.device_readings = MagicMock()
        self.library = AsyncMock()
        self.monitors = AsyncMock()
        self.proposals = AsyncMock()
        self.activations = AsyncMock()
        self.datasets = AsyncMock()
        self.runs = AsyncMock()
        self.metrics = AsyncMock()

    def overrides(self) -> dict:
        return {
            get_db_async: returning(AsyncMock()),
            providers.get_catalogue_data_service: returning(self.data),
            providers.get_pipeline_library: returning(self.library),
            providers.get_radar_orchestration_service: returning(self.monitors),
            providers.get_pipeline_proposals: returning(self.proposals),
            providers.get_pipeline_activations: returning(self.activations),
            providers.get_dojo_datasets: returning(self.datasets),
            providers.get_dojo_runs: returning(self.runs),
            providers.get_dojo_metrics: returning(self.metrics),
        }

    def asked(self) -> list:
        return [call for store in vars(self).values() for call in store.mock_calls]


@pytest.fixture
def stores():
    return Stores()


@pytest.fixture
def key(monkeypatch) -> Agent:
    """The agent behind ``BY_KEY``; a member signs in with ``BY_MEMBER``."""
    held = agent()
    Callers(monkeypatch, agent=held, member=member())
    return held


@pytest.fixture
def gateway(stores):
    limiter.reset()
    app = build_app(AppSettings(APP_NAME="off-key-test"))
    app.dependency_overrides |= stores.overrides()
    yield app
    limiter.reset()


@pytest.fixture
def no_pause(monkeypatch):
    """A tool that waits for something to finish asks again at once."""
    monkeypatch.setattr(mcp_tools, "PAUSE", 0.0)


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
async def test_an_agent_finds_the_tools_its_key_allows(gateway, key):
    async with connected(gateway) as client:
        assert client.server_info.name == "off-key"
        assert client.instructions == mcp_tools.INSTRUCTIONS
        tools = (await client.list_tools()).tools
        # The grant is read with every request, so it holds from the next one.
        key.starts = "shadow"
        in_shadow = (await client.list_tools()).tools
        key.starts = "live"
        granted = (await client.list_tools()).tools

    assert [tool.name for tool in tools] == WITHOUT_THE_GRANT
    # A key that starts in shadow only has the same tools as one that starts live.
    assert in_shadow == granted
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
async def test_only_the_key_of_an_agent_opens_the_door(gateway, key, stores):
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
    assert stores.asked() == []


@pytest.mark.asyncio
async def test_a_tool_is_a_call_to_the_api_as_the_agent(gateway, key, stores):
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
    stores.data.devices.return_value = [device]
    stores.data.device_readings.return_value = []
    stores.data.profile.return_value = profile
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

    assert stores.data.devices.await_args.kwargs == {"active": True}
    assert stores.data.device_readings.call_args.args == ("pump",)
    assert stores.data.profile.await_args.args == ("r-power",)
    assert stores.data.profile.await_args.kwargs == {"days": 14}
    # Components and designs are worked out in process; nothing is stored.
    assert [call[0] for call in stores.asked()] == [
        "devices",
        "device_readings",
        "profile",
    ]


@pytest.mark.asyncio
async def test_a_refusal_reaches_the_agent_in_the_words_of_the_api(
    gateway, key, stores
):
    design = starter()["definition"]
    start = {"name": "Pump", "definition": design, "bindings": {"value": "r-power"}}
    refusals = (
        # The tool refuses what it does not know, without a call.
        ("drop_database", {}, "There is no tool called drop_database"),
        ("start_monitor", start, "This key may not start monitors"),
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
    assert stores.asked() == []


@pytest.mark.asyncio
async def test_a_design_is_tested_on_history(gateway, key, stores, no_pause):
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
        "definition": {
            "compiled": "long",
            "settings": {"training_window_size": 1200, "calibration_window_size": 360},
        },
        "bindings": [{"slot_id": "value", "series_id": "s1", "series_name": "Power"}],
        "alignment": {},
        "cancel_requested": False,
        "stats": {"missing_reading": 2},
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
    stores.datasets.import_history.return_value = dataset
    stores.datasets.get.return_value = dataset
    stores.runs.create.return_value = run
    stores.runs.get.side_effect = lambda run_id: next(states)
    stores.metrics.run.return_value = metrics
    alarmed = [
        {
            "sequence": n,
            "timestamp": f"2026-03-01T00:0{n}:00Z",
            "phase": "operational",
            "score": 0.9,
            "threshold": 0.5,
            "alarm": True,
        }
        for n in (3, 4, 5, 8)
    ]
    stores.runs.results.return_value = {"items": alarmed, "next_after": None}
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
        copied = stores.datasets.import_history.await_args.args[0]
        assert copied.name == "Test by an agent · last 3 days"
        assert copied.reading_ids == ["r-power"]
        assert copied.end - copied.start == timedelta(days=3)
        # An agent is no member, so neither record names one as its creator.
        assert stores.datasets.import_history.await_args.kwargs == {"created_by": None}
        queue = stores.runs.create.await_args.args[0]
        assert (queue.dataset_id, queue.bindings) == ("d1", {"value": "s1"})
        assert stores.runs.create.await_args.kwargs == {"created_by": None}

        # A changed design runs on the same copy, so the two results compare.
        await client.call_tool("test_design", test | {"dataset_id": "d1"})
        elsewhere = await client.call_tool(
            "test_design",
            {**test, "bindings": {"value": "r-flow"}, "dataset_id": "d1"},
        )
        assert said(elsewhere) == "The dataset holds no values of r-flow"
        assert stores.datasets.import_history.await_count == 1
        assert stores.runs.create.await_count == 2

        # It waits for the run to finish, and spares the agent the compiled design.
        result = said(await client.call_tool("get_test", {"run_id": "run-1"}))
        assert (result["status"], result["alarm_count"]) == ("succeeded", 7)
        assert result["stats"] == {"missing_reading": 2}
        assert "definition" not in result
        assert result["metrics"]["false_alarms_per_day"] == 2
        # Alarmed results in a row are one alarm, listed with when it was.
        assert result["alarms"] == {
            "count": 2,
            "listed": [
                {
                    "start": "2026-03-01T00:03:00Z",
                    "end": "2026-03-01T00:05:00Z",
                    "results": 3,
                },
                {
                    "start": "2026-03-01T00:08:00Z",
                    "end": "2026-03-01T00:08:00Z",
                    "results": 1,
                },
            ],
            "complete": True,
        }
        assert stores.runs.results.await_args.args[1].alarm is True
        # Without labels every alarm is counted false, which the note says.
        assert result["note"].startswith("The dataset has no labels")

        # A replay shorter than the warm-up scores nothing, and says so.
        metrics["scored_from"] = None
        states = iter([run | {"status": "succeeded", "result_count": 300}])
        result = said(await client.call_tool("get_test", {"run_id": "run-1"}))
        assert result["note"].startswith("Nothing was scored: the replay gave 300 ")
        assert "warm-up of 1560 observations" in result["note"]


@pytest.mark.asyncio
async def test_a_design_is_proposed_and_started_only_with_the_grant(
    gateway, key, stores, no_pause
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
    stores.proposals.create.return_value = proposal(replace_service_id="service-9")
    stores.proposals.list.return_value = {"items": [summary]}
    stores.proposals.withdraw.return_value = proposal(status="withdrawn")
    stores.activations.apply.return_value = activation
    stores.activations.get.side_effect = lambda activation_id: next(phases)
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
        handed, author = stores.proposals.create.await_args.args
        assert author is key
        assert handed.name == "Pump vibration"
        assert handed.bindings == {"value": "r-power"}
        assert handed.layout.model_dump(mode="json") == design["layout"]
        assert (handed.test_run_id, handed.replace_service_id) == (
            "run-1",
            "service-9",
        )

        # The room to start is a hint: when it cannot be read, the proposal
        # that was made still comes back.
        stores.proposals.list.side_effect = [RuntimeError("busy")]
        made = said(
            await client.call_tool(
                "propose_design", start | {"reason": "Catches the bearing fault."}
            )
        )
        assert made["id"] == "p1" and "note" not in made
        stores.proposals.list.side_effect = None
        waiting = said(await client.call_tool("list_proposals", {"status": "open"}))
        assert [item["id"] for item in waiting["items"]] == ["p1"]
        assert stores.proposals.list.await_args.args == ("open",)
        taken_back = said(
            await client.call_tool("withdraw_proposal", {"proposal_id": "p1"})
        )
        assert taken_back["status"] == "withdrawn"

        refused = await client.call_tool("start_monitor", start)
        assert said(refused).startswith("This key may not start monitors")
        assert "propose_design" in said(refused)
        assert stores.activations.apply.await_count == 0

        key.starts = "live"
        started = said(await client.call_tool("start_monitor", start))
        assert (started["id"], started["monitor_id"]) == ("activation-1", "service-1")
        [applied] = stores.activations.apply.await_args.args
        assert applied.display_name == "Pump vibration"
        assert applied.bindings == {"value": "r-power"}
        assert applied.replace_service_id is None
        assert applied.shadow is False
        # In shadow the monitor records its alarms and raises none.
        await client.call_tool("start_monitor", start | {"shadow": True})
        assert stores.activations.apply.await_args.args[0].shadow
        # A start is named even where the agent names none, and by the agent's
        # own word where it repeats a call.
        assert len(applied.idempotency_key) == 32
        await client.call_tool("start_monitor", start | {"idempotency_key": "again"})
        again = stores.activations.apply.await_args.args[0]
        assert again.idempotency_key == "again"

        settled = said(
            await client.call_tool("get_start", {"activation_id": "activation-1"})
        )
        assert (settled["phase"], settled["monitor_id"]) == ("succeeded", "service-1")


@pytest.mark.asyncio
async def test_a_design_is_read_from_where_it_is(gateway, key, stores):
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
    stores.library.list.return_value = {"items": [listed]}
    stores.monitors.list_radar_services.return_value = [service]
    stores.library.get.return_value = saved
    stores.proposals.get.return_value = proposal()
    stores.library.service.return_value = runs
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
        assert stores.library.list.await_args.args[0].limit == 100

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


@pytest.mark.asyncio
async def test_an_agent_reads_what_its_key_may_do_and_the_room_to_start(
    gateway, key, stores
):
    stores.proposals.list.return_value = {
        "items": [],
        "capacity": {"running": 2, "limit": 2},
    }
    async with connected(gateway) as client:
        access = said(await client.call_tool("get_access", {}))
        assert access["starts"] == "nothing"
        assert access["may"].startswith("propose")
        assert access["monitors"] == {"running": 2, "limit": 2, "free": 0}
        assert access["open_proposals"] == 0
        assert "places are taken" in access["note"]
        key.starts = "shadow"
        stores.proposals.list.return_value["capacity"] = {"running": 1, "limit": 6}
        access = said(await client.call_tool("get_access", {}))
        assert "shadow" in access["may"]
        assert access["monitors"]["free"] == 5
        assert "note" not in access
