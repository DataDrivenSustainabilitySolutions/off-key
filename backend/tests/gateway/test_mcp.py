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
from off_key_tactic_middleware.domain import ForbiddenError

from tests.support.gateway import BY_KEY, BY_MEMBER, Callers, agent, member, returning

URL = "http://gateway/v1/mcp"
THEN = datetime(2026, 3, 1, tzinfo=UTC).isoformat()
SAID = "2026-03-01T00:00:00Z"  # THEN, as an answer of the API writes it
LATER = datetime(2026, 3, 1, 1, tzinfo=UTC).isoformat()
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
    "list_my_tests",
    "delete_mine",
    "get_dataset",
    "get_dataset_values",
    "profile_series",
    "propose_labels",
    "get_suite",
    "create_suite",
    "run_study",
    "get_study",
    "list_monitors",
    "get_monitor",
    "get_values",
    "get_monitor_alarms",
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
        self.labels = AsyncMock()
        self.pending = AsyncMock()
        self.suites = AsyncMock()

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
            providers.get_dojo_labels: returning(self.labels),
            providers.get_dojo_pending_labels: returning(self.pending),
            providers.get_dojo_suites: returning(self.suites),
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
    answer = json.loads(content.text)
    return answer["error"] if result.is_error else answer


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
        "stop_monitor",
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
        "delete_mine",
        "propose_labels",
        "create_suite",
        "run_study",
        "start_monitor",
        "stop_monitor",
    }
    # Deleting cannot be undone, and only what the key made can be deleted.
    assert {tool.name for tool in granted if tool.annotations.destructive_hint} == {
        "delete_mine"
    }
    # An agent reads the whole list with every session, so it stays short. The
    # suite and study tools raised it from 31,500 for the loop of comparing
    # candidates over many datasets, and the rationale's one-line summary,
    # which members read first, to 35,500; the fault-injection protocol's
    # fault shapes and suite settings to 37,000.
    listing = [tool.model_dump(mode="json", exclude_none=True) for tool in granted]
    assert len(json.dumps(listing)) < 37_000


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
    readings = [
        {"id": key, "label": key, "broker_id": "plant", "topic": f"pump/{key}"}
        for key in ("r-power", "r-flow")
    ]
    stores.data.device_readings.return_value = readings
    stores.monitors.list_radar_services.return_value = [
        {
            "id": "service-1",
            "display_name": "Pump power",
            "stream_ids": ["r-power"],
            "status": True,
        }
    ]
    stores.data.profile.return_value = profile
    stores.data.measurements.return_value = [
        {"timestamp": f"2026-03-01T00:00:{second:02}Z", "value": 1.0, "created": THEN}
        for second in (20, 10, 0)
    ]
    async with connected(gateway) as client:
        devices = said(await client.call_tool("list_devices", {"active": True}))
        assert [item["id"] for item in devices] == ["pump"]
        # Each reading says which running monitor holds it.
        listed = said(await client.call_tool("list_readings", {"device_id": "pump"}))
        assert [item.get("held_by") for item in listed] == [
            {"id": "service-1", "name": "Pump power"},
            None,
        ]
        # And how often its values were recorded, newest first in the answer.
        assert [item["interval_seconds"] for item in listed] == [10.0, 10.0]
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
                            # The starter's example Lags step follows the source.
                            "before": "lags",
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
        assert edited["report"]["valid"]
        assert {item["code"] for item in edited["report"]["issues"]} <= {
            "point_detector_without_time"
        }
        # The report leaves out what the agent holds and what says nothing:
        # the design, defaults, and the features after the detector.
        assert edited["report"].keys() == {
            "valid",
            "issues",
            "order",
            "features",
            # The smoothing step holds the first observations back.
            "preparation_observations",
            "ready_after",
        }
        assert edited["report"]["features"].keys() == {
            "input",
            "prepare_smooth_1",
            "lags",
            "detector",
        }
        assert "note" not in edited
        empty = said(
            await client.call_tool(
                "edit_design",
                {"edits": [{"op": "add_input", "id": "power"}]},
            )
        )
        assert empty["note"].startswith("The design has no detector yet.")
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
        "measurements",
        "measurements",
        "profile",
        "list_radar_services",
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
        "created_by_agent": "Claude",
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
    around = [
        {
            "sequence": n,
            "timestamp": f"2026-03-01T00:{n:02}:00Z",
            "phase": "operational",
            "score": 0.2,
            "threshold": 0.5,
            "alarm": False,
        }
        for n in (1, 2)
    ]

    async def results(run_id, query):
        page = alarmed if query.alarm else around
        return {"items": page, "next_after": None}

    stores.runs.results.side_effect = results
    stores.monitors.list_radar_services.return_value = [
        {"id": "m1", "display_name": "Pump", "stream_ids": ["r-power"], "status": True}
    ]
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
            "notes",
        }
        # Said before it runs: the warm-up outlasts the replay, and the reading
        # is held by a running monitor.
        warm_up, held = queued["notes"]
        assert warm_up.startswith("The replay holds about 100 observations, fewer")
        assert "warm-up of 1560" in warm_up
        assert held.startswith("A running monitor already holds r-power (monitor m1)")
        assert (queued["run_id"], queued["dataset_id"]) == ("run-1", "d1")
        # The values of the readings are copied, and each input takes its own.
        copied = stores.datasets.import_history.await_args.args[0]
        assert copied.name == "Test by an agent · last 3 days"
        assert copied.reading_ids == ["r-power"]
        assert copied.end - copied.start == timedelta(days=3)
        # An agent is no member, so neither record names one as its creator;
        # each names the agent, whose key alone may delete it.
        assert stores.datasets.import_history.await_args.kwargs == {
            "created_by": None,
            "created_by_agent": key,
        }
        queue = stores.runs.create.await_args.args[0]
        assert (queue.dataset_id, queue.bindings) == ("d1", {"value": "s1"})
        assert stores.runs.create.await_args.kwargs == {
            "created_by": None,
            "created_by_agent": key,
        }

        # A changed design runs on the same copy, so the two results compare.
        await client.call_tool("test_design", test | {"dataset_id": "d1"})
        elsewhere = await client.call_tool(
            "test_design",
            {**test, "bindings": {"value": "r-flow"}, "dataset_id": "d1"},
        )
        assert said(elsewhere) == "The dataset holds no values of r-flow"
        assert stores.datasets.import_history.await_count == 1
        assert stores.runs.create.await_count == 2

        # Faults are written into a labelled copy, and the run replays the copy.
        series = dataset["series"][0] | {"id": "s2"}
        stores.datasets.inject_faults.return_value = dataset | {
            "id": "d2",
            "series": [series],
        }
        step = {
            "kind": "step",
            "reading": "r-power",
            "start": "2026-03-01T00:10:00Z",
            "end": "2026-03-01T00:20:00Z",
            "size": 5,
        }
        faulted = said(
            await client.call_tool(
                "test_design", test | {"dataset_id": "d1", "faults": [step]}
            )
        )
        assert faulted["dataset_id"] == "d2"
        source, written = stores.datasets.inject_faults.await_args.args
        assert source == "d1"
        assert written.name == "Test by an agent · 1 injected fault"
        assert [(item.kind, item.series_id, item.size) for item in written.faults] == [
            ("step", "s1", 5.0)
        ]
        assert stores.runs.create.await_args.args[0].bindings == {"value": "s2"}
        unbound = await client.call_tool(
            "test_design",
            test | {"dataset_id": "d1", "faults": [step | {"reading": "r-flow"}]},
        )
        assert said(unbound) == ("Faults name readings the test does not bind: r-flow")

        # It waits for the run to finish, and spares the agent the compiled design.
        result = said(await client.call_tool("get_test", {"run_id": "run-1"}))
        assert (result["status"], result["alarming_results"]) == ("succeeded", 7)
        # One name for the run in both tools.
        assert result["run_id"] == "run-1" and "id" not in result
        assert result["created_by"] == "Agent · Claude"
        assert result["metrics"]["alarming_results"] == 7
        # What the results are, not the starter the design came from.
        assert result["results_are"] == "scores against a threshold"
        assert "strategy" not in result and "strategy" not in result["metrics"]
        assert result["stats"] == {"missing_reading": 2}
        assert result["stats_meaning"] == {
            "missing_reading": "no value of another bound reading had arrived yet"
        }
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
            # Two alarms in the day that was scored.
            "per_day": 2.0,
            # Scores from a few results before to a few after the first alarms.
            "excerpts": {
                "columns": ["time", "score", "threshold", "alarm"],
                "around": [
                    {
                        "start": start,
                        "rows": [
                            ["2026-03-01T00:01:00Z", 0.2, 0.5, False],
                            ["2026-03-01T00:02:00Z", 0.2, 0.5, False],
                        ],
                    }
                    for start in ("2026-03-01T00:03:00Z", "2026-03-01T00:08:00Z")
                ],
            },
        }
        asked = [call.args[1] for call in stores.runs.results.await_args_list]
        assert asked[0].alarm is True
        assert [(item.after, item.limit) for item in asked[1:]] == [(None, 12), (1, 13)]
        # Without labels every alarm is counted false, which the note says.
        assert result["note"].startswith("The dataset has no labels")

        # A replay shorter than the warm-up scores nothing, and says so.
        metrics["scored_from"] = None
        states = iter([run | {"status": "succeeded", "result_count": 300}])
        result = said(await client.call_tool("get_test", {"run_id": "run-1"}))
        assert result["note"].startswith("Nothing was scored: the replay gave 300 ")
        assert "warm-up of 1560 observations" in result["note"]
        # A test without alarms still answers them as an object.
        assert result["alarms"] == {"count": 0, "listed": [], "complete": True}


def dojo_run(**fields) -> dict:
    return {
        "id": "run-1",
        "dataset_id": "d1",
        "name": "Test by an agent",
        "status": "succeeded",
        "strategy": "adaptive_stream",
        "points_total": 100,
        "points_read": 100,
        "result_count": 90,
        "alarm_count": 0,
        "error": None,
        "created_by": None,
        "created_by_agent": "Designer",
        "created_at": THEN,
        "started_at": THEN,
        "finished_at": THEN,
        "definition": {},
        "bindings": [],
        "alignment": {},
        "cancel_requested": False,
        "stats": {},
    } | fields


@pytest.mark.asyncio
async def test_an_agent_cleans_up_what_it_made(gateway, key, stores, no_pause):
    stores.datasets.list.return_value = {
        "items": [
            {
                "id": "d1",
                "name": "Pump · last 3 days",
                "description": "",
                "origin": "history",
                "point_count": 100,
                "series_count": 1,
                "start_at": THEN,
                "end_at": THEN,
                "created_by": None,
                "created_by_agent": "Designer",
                "created_at": THEN,
            }
        ],
        "next_offset": None,
    }
    summary = {
        key: value
        for key, value in dojo_run().items()
        if key
        not in {"definition", "bindings", "alignment", "cancel_requested", "stats"}
    }
    stores.runs.list.return_value = {"items": [summary], "next_offset": None}
    async with connected(gateway) as client:
        listed = said(await client.call_tool("list_my_tests", {}))
        assert listed == {
            "datasets": [
                {"id": "d1", "name": "Pump · last 3 days", "created_at": SAID}
            ],
            "tests": [
                {
                    "run_id": "run-1",
                    "dataset_id": "d1",
                    "name": "Test by an agent",
                    "status": "succeeded",
                    "created_at": SAID,
                }
            ],
            "more": False,
        }
        # Each list is the key's own, read as the key.
        query, caller = stores.datasets.list.await_args.args
        assert (query.mine, caller) == (True, key)
        assert stores.runs.list.await_args.args[0].mine

        # A test still running is cancelled, and deleted once it has ended.
        states = iter([dojo_run(status="running"), dojo_run(status="cancelled")])
        stores.runs.get.side_effect = lambda run_id: next(states)
        stores.runs.cancel.return_value = dojo_run(status="running")
        deleted = said(await client.call_tool("delete_mine", {"run_id": "run-1"}))
        assert deleted == {"deleted": {"run_id": "run-1"}}
        assert stores.runs.cancel.await_args.args == ("run-1", key)
        assert stores.runs.remove.await_args.args == ("run-1", key)

        stores.runs.list.return_value = {"items": [], "next_offset": None}
        await client.call_tool("delete_mine", {"dataset_id": "d1"})
        assert stores.datasets.remove.await_args.args == ("d1", key)
        await client.call_tool("delete_mine", {"proposal_id": "p1"})
        assert stores.proposals.remove.await_args.args == ("p1", key)

        for named in ({}, {"run_id": "run-1", "dataset_id": "d1"}):
            refused = await client.call_tool("delete_mine", named)
            assert said(refused) == (
                "Name one of run_id, dataset_id, study_id, suite_id or proposal_id"
            )
        # What the key may not delete is refused in the API's words.
        stores.runs.get.side_effect = None
        stores.runs.get.return_value = dojo_run()
        stores.runs.remove.side_effect = ForbiddenError(
            "A key cancels and deletes only the runs it queued"
        )
        refused = await client.call_tool("delete_mine", {"run_id": "run-2"})
        assert said(refused) == "A key cancels and deletes only the runs it queued"


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
                | WHY
                | {
                    "test_run_id": "run-1",
                    "replace_monitor_id": "service-9",
                },
            )
        )
        assert (proposed["id"], proposed["replace_monitor_id"]) == ("p1", "service-9")
        handed, author = stores.proposals.create.await_args.args
        assert author is key
        assert handed.name == "Pump vibration"
        # The rationale is the proposal's reason, and kept as four fields.
        assert handed.rationale.model_dump() == WHY["rationale"]
        assert handed.reason == WHY["rationale"]["watches"]
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
                "propose_design", start | WHY | {"reason": "Catches the bearing fault."}
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

        refused = await client.call_tool("start_monitor", start | WHY)
        assert said(refused).startswith("This key may not start monitors")
        assert "propose_design" in said(refused)
        assert stores.activations.apply.await_count == 0

        key.starts = "live"
        # The rationale is required, and each field is short.
        unexplained = await client.call_tool("start_monitor", start)
        assert unexplained.is_error and "rationale" in said(unexplained)
        rambling = WHY["rationale"] | {"limits": "x" * 201}
        too_long = await client.call_tool(
            "start_monitor", start | {"rationale": rambling}
        )
        assert too_long.is_error and "rationale.limits" in said(too_long)
        assert stores.activations.apply.await_count == 0
        started = said(
            await client.call_tool("start_monitor", start | WHY | {"test_run_id": "t1"})
        )
        assert (started["id"], started["monitor_id"]) == ("activation-1", "service-1")
        # The id of the run inside the monitor is no test's: agents took it for one.
        assert "run_id" not in started
        applied, caller = stores.activations.apply.await_args.args
        assert caller is key
        assert applied.rationale.model_dump() == WHY["rationale"]
        assert applied.test_run_id == "t1"
        assert applied.display_name == "Pump vibration"
        assert applied.bindings == {"value": "r-power"}
        assert applied.replace_service_id is None
        assert applied.shadow is False
        # In shadow the monitor records its alarms and raises none.
        await client.call_tool("start_monitor", start | WHY | {"shadow": True})
        assert stores.activations.apply.await_args.args[0].shadow
        # A start is named even where the agent names none, and by the agent's
        # own word where it repeats a call.
        assert len(applied.idempotency_key) == 32
        await client.call_tool(
            "start_monitor", start | WHY | {"idempotency_key": "again"}
        )
        again = stores.activations.apply.await_args.args[0]
        assert again.idempotency_key == "again"

        settled = said(
            await client.call_tool("get_start", {"activation_id": "activation-1"})
        )
        assert (settled["phase"], settled["monitor_id"]) == ("succeeded", "service-1")
        assert "run_id" not in settled


WHY = {
    "rationale": {
        "watches": "Pump vibration rising above its usual daily band.",
        "why": "A moving Mahalanobis distance on vibration and current.",
        "evidence": "1 alarm in 9 scored hours of the last week; no labels.",
        "limits": "First mornings alarm until it has seen a few days.",
    }
}


def monitor(**fields) -> dict:
    return {
        "id": "service-1",
        "display_name": "Pump vibration",
        "stream_ids": ["r-power"],
        "status": True,
        "shadow": True,
        "created_at": THEN,
        "operational_status": {"stage": "running"},
        "origin": {
            "author": "Designer",
            "author_kind": "agent",
            "rationale": WHY["rationale"],
            "test_run_id": "t1",
            "history": [
                {
                    "event": "started",
                    "author": "Designer",
                    "author_kind": "agent",
                    "rationale": WHY["rationale"],
                    "test_run_id": "t1",
                    "shadow": True,
                    "at": THEN,
                }
            ],
        },
    } | fields


@pytest.mark.asyncio
async def test_an_agent_finds_watches_and_stops_its_own_monitors(gateway, key, stores):
    theirs = monitor(
        id="service-2",
        stream_ids=["r-flow"],
        shadow=False,
        origin={"author": "admin@example.com", "author_kind": "member"},
    )
    stores.monitors.list_radar_services.return_value = [monitor(), theirs]
    stores.monitors.get_radar_service.return_value = monitor()
    stores.monitors.stop_monitor_as.return_value = True
    async with connected(gateway) as client:
        listed = said(await client.call_tool("list_monitors", {}))
        assert [(item["id"], item["mine"]) for item in listed] == [
            ("service-1", True),
            ("service-2", False),
        ]
        assert listed[0]["started_by"] == {"author": "Designer", "kind": "agent"}
        assert listed[1]["reading_ids"] == ["r-flow"]
        mine = said(await client.call_tool("list_monitors", {"mine": True}))
        assert [item["id"] for item in mine] == ["service-1"]

        one = said(await client.call_tool("get_monitor", {"monitor_id": "service-1"}))
        assert one["mine"] and one["shadow"]
        assert one["origin"]["rationale"] == WHY["rationale"]
        assert one["origin"]["test_run_id"] == "t1"
        assert stores.monitors.get_radar_service.await_args.args == ("service-1",)

        # Stopping is for a key that may start monitors, with a note on why.
        refused = await client.call_tool(
            "stop_monitor", {"monitor_id": "service-1", "note": "Too noisy."}
        )
        assert said(refused).startswith("This key may not start monitors")
        key.starts = "shadow"
        unexplained = await client.call_tool(
            "stop_monitor", {"monitor_id": "service-1"}
        )
        assert unexplained.is_error and "note" in said(unexplained)
        stopped = said(
            await client.call_tool(
                "stop_monitor", {"monitor_id": "service-1", "note": "Too noisy."}
            )
        )
        assert stopped == {"monitor_id": "service-1", "status": "stopped"}
    monitor_id, caller, note = stores.monitors.stop_monitor_as.await_args.args
    assert (monitor_id, caller, note) == ("service-1", key, "Too noisy.")


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
                    "shadow": False,
                    "started_by": None,
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
    stores.monitors.list_radar_services.return_value = [
        {"id": "m1", "status": True, "shadow": True},
        {"id": "m2", "status": True},
    ]
    async with connected(gateway) as client:
        access = said(await client.call_tool("get_access", {}))
        assert access["starts"] == "nothing"
        assert access["may"].startswith("propose")
        assert access["monitors"] == {
            "running": 2,
            "limit": 2,
            "free": 0,
            "live": 1,
            "shadow": 1,
        }
        assert access["open_proposals"] == 0
        assert "places are taken" in access["note"]
        key.starts = "shadow"
        stores.proposals.list.return_value["capacity"] = {"running": 1, "limit": 6}
        access = said(await client.call_tool("get_access", {}))
        assert "shadow" in access["may"]
        assert access["monitors"]["free"] == 5
        assert "note" not in access


@pytest.mark.asyncio
async def test_an_agent_reads_values_and_a_monitors_alarms(gateway, key, stores):
    stores.data.measurement_buckets.return_value = {
        "representation": "mean",
        "points": [
            {
                "timestamp": "2026-03-01T00:00:00Z",
                "value": 4.0,
                "minimum": 1.0,
                "maximum": 9.0,
                "count": 12,
                "start": "2026-03-01T00:00:00Z",
                "end": "2026-03-01T00:01:00Z",
            }
        ],
        "interval_ms": 60_000,
        "sample_count": 12,
    }
    evidence = [
        {
            "monitor_id": "service-1",
            "timestamp": f"2026-03-01T00:0{n}:00Z",
            "sequence_number": n,
            "reading_ids": ["r-power"],
            "input_timestamps": {},
            "strategy": "adaptive_stream",
            "anomaly_score": score,
            "threshold": 0.5,
            "alarm": True,
            "muted": True,
            "created": f"2026-03-01T00:0{n}:01Z",
        }
        for n, score in ((3, 0.7), (4, 0.9), (7, 0.6))
    ]
    stores.data.chart_evidence.return_value = evidence
    stores.monitors.get_radar_service.return_value = monitor()
    async with connected(gateway) as client:
        values = said(
            await client.call_tool(
                "get_values",
                {"reading_id": "r-power", "start": THEN, "points": 50},
            )
        )
        assert values == {
            "reading_id": "r-power",
            "columns": ["time", "mean", "min", "max", "count"],
            "rows": [["2026-03-01T00:00:00Z", 4.0, 1.0, 9.0, 12]],
            "stretch_seconds": 60.0,
        }
        [reading], window = stores.data.measurement_buckets.await_args
        assert reading == "r-power"
        # Real values only, about as many as asked for: never a mean.
        assert (window["buckets"], window["view"]) == (10, "raw")
        await client.call_tool(
            "get_values", {"reading_id": "r-power", "start": THEN, "points": 500}
        )
        assert stores.data.measurement_buckets.await_args.kwargs["buckets"] == 42

        alarms = said(
            await client.call_tool("get_monitor_alarms", {"monitor_id": "service-1"})
        )
        assert alarms["count"] == 2 and alarms["shadow"] and alarms["complete"]
        assert alarms["listed"] == [
            {
                "start": "2026-03-01T00:03:00Z",
                "end": "2026-03-01T00:04:00Z",
                "results": 2,
                "score": 0.9,
                "threshold": 0.5,
                "muted": True,
            },
            {
                "start": "2026-03-01T00:07:00Z",
                "end": "2026-03-01T00:07:00Z",
                "results": 1,
                "score": 0.6,
                "threshold": 0.5,
                "muted": True,
            },
        ]
        asked = stores.data.chart_evidence.await_args.kwargs
        assert (asked["service_id"], asked["alarm"], asked["stream_ids"]) == (
            "service-1",
            True,
            ["r-power"],
        )


def test_a_design_of_rules_alone_warms_up_only_its_calibration():
    settings = {"training_window_size": 500, "calibration_window_size": 20}
    dataset = {
        "start_at": "2026-11-01T00:00:00+00:00",
        "end_at": "2026-11-02T00:00:00+00:00",
    }

    def design(*components, calibration=True):
        return {
            "settings": settings,
            "nodes": [{"kind": "detector", "component": item} for item in components]
            + (
                [{"kind": "calibration", "component": "calibrate.split"}]
                if calibration
                else []
            ),
        }

    rules = mcp_tools._warm_up(design("rule.score"), dataset, 200, 1)
    assert rules.startswith("Warm-up takes 20 of about 200 observations")
    learned = mcp_tools._warm_up(design("rule.score", "detector:x"), dataset, 200, 1)
    assert "warm-up of 520" in learned
    # A rule on a fixed threshold has no calibration step to fill.
    fixed = mcp_tools._warm_up(design("rule.score", calibration=False), dataset, 200, 1)
    assert fixed.startswith("No warm-up: rules on a fixed threshold")


def _alarm(sequence: int, minute: int) -> dict:
    return {"sequence": sequence, "timestamp": f"2026-03-01T00:{minute:02}:00Z"}


def test_a_test_lists_its_false_alarms_first_and_marks_the_caught_ones():
    results = [_alarm(1, 1), _alarm(2, 2), _alarm(10, 10), _alarm(20, 20)]
    labels = [{"start_at": "2026-03-01T00:09:00Z", "end_at": "2026-03-01T00:11:00Z"}]
    alarms, around = mcp_tools._episodes(
        results, True, {"labels": labels, "evaluated_seconds": 43200.0}
    )
    assert alarms["count"] == 3 and alarms["per_day"] == 6.0
    assert [
        (item["start"][11:16], item["false_alarm"]) for item in alarms["listed"]
    ] == [
        ("00:01", True),
        ("00:20", True),
        ("00:10", False),
    ]
    # The scores are read around the false alarms first, too.
    assert around[0]["first"] == 1


async def test_a_test_counts_alarms_beyond_one_page_of_results():
    pages = {
        None: {"items": [_alarm(1, 1), _alarm(2, 2)], "next_after": 2},
        2: {"items": [_alarm(3, 3), _alarm(9, 9)], "next_after": None},
    }

    class Pages:
        async def get(self, path, query):
            return pages[query.get("after")]

    results, complete = await mcp_tools._alarmed(Pages(), "/v1/dojo/runs/run-1")
    assert complete and len(results) == 4
    alarms, _ = mcp_tools._episodes(results, complete)
    # One alarm runs on across the pages instead of being cut where one ends.
    assert [item["end"][11:16] for item in alarms["listed"]] == ["00:03", "00:09"]


async def test_an_agent_reads_a_dataset_and_proposes_labels_for_review(
    gateway, stores, key
):
    series = {
        "id": "s1",
        "position": 0,
        "name": "motor temperature",
        "unit": "°C",
        "reading_id": None,
        "point_count": 2,
        "start_at": THEN,
        "end_at": THEN,
    }
    stores.datasets.get.return_value = {
        "id": "d1",
        "name": "Drives",
        "description": "",
        "origin": "csv",
        "source": {},
        "point_count": 2,
        "series_count": 1,
        "start_at": THEN,
        "end_at": THEN,
        "created_by": 1,
        "created_at": THEN,
        "series": [series],
    }
    label = {
        "id": "l1",
        "dataset_id": "d1",
        "start_at": THEN,
        "end_at": THEN,
        "note": "Overheated",
        "rule": "",
        "suggested_by_agent": None,
        "created_by": 1,
        "created_at": THEN,
    }
    stores.labels.list.return_value = {"items": [label]}
    pending = {
        "id": "p1",
        "dataset_id": "d1",
        "start_at": THEN,
        "end_at": THEN,
        "note": "",
        "rule": "`motor temperature` > 80",
        "created_by": None,
        "created_by_agent": "Claude",
        "created_at": THEN,
    }
    stores.pending.list.return_value = {"items": [pending]}
    stores.datasets.points.return_value = {
        "items": [{"timestamp": THEN, "value": 81.5}],
        "next_after": None,
    }
    stores.datasets.profile.return_value = {
        "series_id": "s1",
        "name": "motor temperature",
        "count": 500,
        "notes": ["It follows a cycle of 24 steps."],
    }
    stores.datasets.profile_dataset.return_value = {
        "dataset_id": "d1",
        "name": "Motor",
        "series": [{"series_id": "s1", "name": "motor temperature", "count": 500}],
    }
    made = {"items": [pending], "skipped": 0, "truncated": False, "replaced": 0}
    stores.pending.propose.return_value = made
    stores.pending.propose_by_rule.return_value = made
    async with connected(gateway) as client:
        dataset = said(await client.call_tool("get_dataset", {"dataset_id": "d1"}))
        values = said(
            await client.call_tool(
                "get_dataset_values",
                {"dataset_id": "d1", "series": "motor temperature", "limit": 5},
            )
        )
        unknown = await client.call_tool(
            "get_dataset_values", {"dataset_id": "d1", "series": "speed"}
        )
        profile = said(
            await client.call_tool(
                "profile_series", {"dataset_id": "d1", "series": "motor temperature"}
            )
        )
        whole = said(await client.call_tool("profile_series", {"dataset_id": "d1"}))
        by_rule = said(
            await client.call_tool(
                "propose_labels",
                {"dataset_id": "d1", "condition": "`motor temperature` > 80"},
            )
        )
        intervals = said(
            await client.call_tool(
                "propose_labels",
                {
                    "dataset_id": "d1",
                    "labels": [{"start_at": THEN, "end_at": LATER}],
                    "rule": "Where the motor ran hot",
                    "replace": True,
                },
            )
        )
        both = await client.call_tool(
            "propose_labels",
            {"dataset_id": "d1", "condition": "speed > 1", "labels": []},
        )
    assert [item["name"] for item in dataset["series"]] == ["motor temperature"]
    assert dataset["labels"][0]["note"] == "Overheated"
    assert dataset["pending_labels"][0]["created_by_agent"] == "Claude"
    assert values["rows"] == [[SAID, 81.5]]
    assert stores.datasets.points.await_args.args[:2] == ("d1", "s1")
    assert unknown.is_error and "motor temperature" in said(unknown)
    assert profile["count"] == 500 and profile["autocorrelation"] == []
    assert stores.datasets.profile.await_args.args == ("d1", "s1")
    assert whole["series"][0]["values"] is None and whole["pairs"] == []
    assert stores.datasets.profile_dataset.await_args.args == ("d1",)
    assert by_rule == intervals
    assert [item["rule"] for item in by_rule["items"]] == ["`motor temperature` > 80"]
    assert both.is_error
    dataset_id, rule, caller = stores.pending.propose_by_rule.await_args.args
    assert (dataset_id, rule.condition, caller) == (
        "d1",
        "`motor temperature` > 80",
        key,
    )
    dataset_id, proposal, _ = stores.pending.propose.await_args.args
    assert (proposal.rule, proposal.replace, len(proposal.labels)) == (
        "Where the motor ran hot",
        True,
        1,
    )


def totals(vus_pr: float | None = None) -> dict:
    return {
        "runs_scored": 2 if vus_pr is not None else 0,
        "labels_scored": 2,
        "labels_detected": 1,
        "detection_rate": 0.5,
        "median_false_alarms_per_day": 1.0,
        "pr_auc": vus_pr,
        "pr_auc_runs": 2,
        "vus_pr": vus_pr,
        "vus_pr_runs": 2,
        "auroc": vus_pr,
        "auroc_runs": 2,
        "top1_hits": 1,
        "top1_runs": 2,
    }


def study(study_id: str = "st1", **fields) -> dict:
    return {
        "id": study_id,
        "suite_id": "su1",
        "name": "Mahalanobis",
        "strategy": "adaptive_stream",
        "runs": {"succeeded": 2},
        "complete": True,
        "totals": totals(0.5),
        "metrics_pending": 0,
        "created_by": None,
        "created_by_agent": "Designer",
        "created_at": THEN,
    } | fields


def study_view(**fields) -> dict:
    metrics = {
        "run_id": "run-1",
        "run_name": "Mahalanobis",
        "strategy": "adaptive_stream",
        "scored_from": THEN,
        "scored_to": LATER,
        "labels_total": 1,
        "labels_scored": 1,
        "labels_detected": 1,
        "detection_rate": 1.0,
        "median_delay_seconds": 0.0,
        "max_delay_seconds": 0.0,
        "alarm_count": 2,
        "false_alarms": 0,
        "evaluated_seconds": 3000.0,
        "false_alarms_per_day": 0.0,
        "scores": None,
        "labels": [],
    }
    items = [
        {
            "dataset_id": "d1",
            "dataset_name": "Pump A",
            "run_id": "run-1",
            "status": "succeeded",
            "error": None,
            "metrics": metrics,
        }
    ]
    return study(**fields) | {
        "definition": {},
        "bindings": {},
        "alignment": {"hold_intervals": 3, "minimum_hold_seconds": 30},
        "items": items,
    }


@pytest.mark.asyncio
async def test_an_agent_runs_and_compares_studies_over_a_suite(
    gateway, key, stores, no_pause
):
    suite = {
        "id": "su1",
        "name": "Pump faults",
        "description": "",
        "derived_from": None,
        "datasets": 1,
        "studies": 2,
        "created_by": None,
        "created_by_agent": "Designer",
        "reviewed": False,
        "created_at": THEN,
        "items": [
            {
                "dataset_id": "d1",
                "name": "Pump A",
                "origin": "history",
                "series_names": ["power"],
                "point_count": 100,
                "labels": 1,
            }
        ],
        "leaderboard": [study()],
        "unfinished": [study("st2", complete=False, runs={"running": 1})],
    }
    stores.suites.list_suites.return_value = {
        "items": [
            {
                k: v
                for k, v in suite.items()
                if k not in {"items", "leaderboard", "unfinished"}
            }
        ],
        "next_offset": None,
    }
    stores.suites.get_suite.return_value = suite
    stores.suites.create_suite.return_value = suite
    stores.suites.create_fault_suite.return_value = suite
    stores.suites.create_study.return_value = study_view()
    # The study is read until its runs end and their metrics are in.
    states = iter([study_view(runs={"running": 1}, complete=False), study_view()])
    stores.suites.get_study.side_effect = lambda *args, **kwargs: next(states)
    stores.suites.compare_studies.return_value = {
        "suite_id": "su1",
        "metric": "vus_pr",
        "baseline": "st2",
        "challenger": "st1",
        "datasets": [],
        "compared": 6,
        "wins": 6,
        "losses": 0,
        "ties": 0,
        "mean_delta": 0.2,
        "median_delta": 0.2,
        "p_value": 0.03125,
    }
    async with connected(gateway) as client:
        listed = said(await client.call_tool("get_suite", {}))
        read = said(await client.call_tool("get_suite", {"suite_id": "su1"}))
        made = said(
            await client.call_tool(
                "create_suite", {"name": "Pump faults", "dataset_ids": ["d1"]}
            )
        )
        faulted = said(
            await client.call_tool(
                "create_suite",
                {"name": "Pump faults", "faults_of": "d1", "copies": 4, "seed": 3},
            )
        )
        neither = await client.call_tool("create_suite", {"name": "Empty"})
        queued = said(
            await client.call_tool(
                "run_study",
                {
                    "suite_id": "su1",
                    "definition": starter()["definition"],
                    "bindings": {"value": "power"},
                },
            )
        )
        studied = said(await client.call_tool("get_study", {"study_id": "st1"}))
        assert stores.suites.get_study.await_count == 2
        stores.suites.get_study.side_effect = None
        stores.suites.get_study.return_value = study_view()
        compared = said(
            await client.call_tool(
                "get_study", {"study_id": "st1", "compare_with": "st2"}
            )
        )
    assert listed["suites"][0] == {
        "id": "su1",
        "name": "Pump faults",
        "description": "",
        "datasets": 1,
        "studies": 2,
        "reviewed": False,
    }
    assert read["datasets"][0]["series_names"] == ["power"]
    assert [item["study_id"] for item in read["leaderboard"]] == ["st1"]
    assert read["unfinished"][0]["complete"] is False
    assert made == {"suite_id": "su1", "datasets": 1}
    request = stores.suites.create_suite.await_args.args[0]
    assert request.dataset_ids == ["d1"]
    assert faulted == {"suite_id": "su1", "datasets": 1}
    request = stores.suites.create_fault_suite.await_args.args[0]
    assert (request.dataset_id, request.copies, request.seed) == ("d1", 4, 3)
    assert neither.is_error and "dataset_ids or faults_of" in said(neither)
    assert queued == {"study_id": "st1", "runs": 1}
    request = stores.suites.create_study.await_args.args[0]
    assert (request.suite_id, request.bindings) == ("su1", {"value": "power"})
    assert studied["complete"] is True and studied["vus_pr"] == 0.5
    assert studied["datasets"][0]["detected"] == "1 of 1"
    comparison = compared["comparison"]
    assert (comparison["wins"], comparison["p_value"]) == (6, 0.03125)
    suite_id, query = stores.suites.compare_studies.await_args.args
    assert (suite_id, query.baseline, query.challenger, query.metric) == (
        "su1",
        "st2",
        "st1",
        "vus_pr",
    )


def protocol_report() -> dict:
    level = {
        "level": 2.0,
        "faults": 2,
        "scored": 2,
        "caught": 1,
        "confounded": 0,
        "rate": 0.5,
        "low": 0.09,
        "high": 0.91,
        "simple_rules": 0,
    }
    family = {
        "family": "step",
        "title": "Sudden step",
        "measure": "sigmas",
        "sanity": False,
        "faults": 2,
        "scored": 2,
        "caught": 1,
        "chance_detections": 0.0,
        "adjusted_detection_rate": 0.5,
        "half": 2.0,
        "ninety": None,
        "median_delay_seconds": 60.0,
        "median_sigmas_at_detection": None,
        "simple_rules_caught": 0,
        "levels": [level],
    }
    return {
        "protocol": "screening-v1",
        "version": 1,
        "purpose": "test",
        "seed": None,
        "warmup_values": 200,
        "window_values": 40,
        "clean_run_id": "run-0",
        "false_alarms_per_day": 0.4,
        "alarm_share": 0.002,
        "budget_per_day": 1.0,
        "budget_share": 0.01,
        "within_budget": True,
        "adjusted_detection_rate": 0.5,
        "faults": 2,
        "caught": 1,
        "simple_rules_caught": 0,
        "sanity_missed": 0,
        "untestable": [],
        "families": [family],
        "headline": "0.4 false alarms a day; catches sudden step from 2σ.",
    }


@pytest.mark.asyncio
async def test_an_agent_reports_on_a_protocol_suite(gateway, key, stores, no_pause):
    """A protocol suite is asked for with the design's windows, and its study
    answers with the profile; a test suite's copies keep their faults hidden."""
    suite = {
        "id": "su1",
        "name": "Screen",
        "description": "",
        "derived_from": None,
        "datasets": 1,
        "studies": 0,
        "created_by": None,
        "created_by_agent": "Designer",
        "reviewed": False,
        "created_at": THEN,
        "items": [],
        "leaderboard": [],
        "unfinished": [],
    }
    stores.suites.create_fault_suite.return_value = suite
    stores.suites.get_study.return_value = study_view() | {
        "protocol": protocol_report()
    }
    stores.datasets.get.return_value = {
        "id": "d2",
        "name": "Screen · copy 1",
        "description": "",
        "origin": "csv",
        "source": {"protocol": {"purpose": "test", "role": "faulted"}},
        "point_count": 2,
        "series_count": 1,
        "start_at": THEN,
        "end_at": THEN,
        "created_by": None,
        "created_at": THEN,
        "series": [],
    }
    label = {
        "dataset_id": "d2",
        "start_at": THEN,
        "end_at": THEN,
        "rule": "",
        "suggested_by_agent": None,
        "created_by": None,
        "created_at": THEN,
    }
    stores.labels.list.return_value = {
        "items": [
            label | {"id": "l1", "note": "Injected step of +2 (+2σ) on power"},
            label | {"id": "l2", "note": "known trip"},
        ]
    }
    stores.pending.list.return_value = {"items": []}
    async with connected(gateway) as client:
        await client.call_tool(
            "create_suite",
            {
                "name": "Screen",
                "faults_of": "d1",
                "protocol": "screening-v1",
                "purpose": "test",
                "warmup_values": 200,
                "window_values": 40,
            },
        )
        studied = said(await client.call_tool("get_study", {"study_id": "st1"}))
        dataset = said(await client.call_tool("get_dataset", {"dataset_id": "d2"}))
    request = stores.suites.create_fault_suite.await_args.args[0]
    assert (request.protocol, request.purpose) == ("screening-v1", "test")
    assert (request.warmup_values, request.window_values) == (200, 40)
    report = studied["protocol"]
    assert report["headline"].startswith("0.4 false alarms a day")
    assert report["within_budget"] is True
    (family,) = report["families"]
    assert (family["family"], family["half"], family["by_level"]) == (
        "Sudden step",
        2.0,
        [[2.0, 1, 2]],
    )
    # With the profile, only runs that did not succeed are listed.
    assert studied["datasets"] == []
    # The injected fault's place is kept from the key; a known problem is not.
    assert [item["note"] for item in dataset["labels"]] == ["known trip"]


@pytest.mark.asyncio
async def test_an_agent_deletes_its_study_and_suite(gateway, key, stores, no_pause):
    states = iter([study_view(runs={"running": 1}), study_view(runs={"cancelled": 1})])
    stores.suites.get_study.side_effect = lambda *args, **kwargs: next(states)
    stores.suites.cancel_study.return_value = study_view(runs={"running": 1})
    stores.suites.list_studies.return_value = {"items": [], "next_offset": None}
    async with connected(gateway) as client:
        study_gone = said(await client.call_tool("delete_mine", {"study_id": "st1"}))
        suite_gone = said(await client.call_tool("delete_mine", {"suite_id": "su1"}))
    assert study_gone == {"deleted": {"study_id": "st1"}}
    assert stores.suites.cancel_study.await_args.args == ("st1", key)
    assert stores.suites.remove_study.await_args.args == ("st1", key)
    assert suite_gone == {"deleted": {"suite_id": "su1"}}
    assert stores.suites.remove_suite.await_args.args == ("su1", key)


@pytest.mark.asyncio
async def test_a_design_is_tested_on_an_uploaded_series_by_name(gateway, key, stores):
    """A benchmark or CSV series was copied from no reading, so it binds by name."""
    stores.datasets.get.return_value = {
        "id": "d1",
        "name": "UCR 001",
        "description": "",
        "origin": "benchmark",
        "point_count": 100,
        "series_count": 1,
        "start_at": THEN,
        "end_at": LATER,
        "created_by": 1,
        "created_at": THEN,
        "source": {},
        "series": [
            {
                "id": "s1",
                "position": 0,
                "name": "value",
                "unit": "",
                "reading_id": None,
                "point_count": 100,
                "start_at": THEN,
                "end_at": LATER,
            }
        ],
    }
    stores.runs.create.return_value = dojo_run(status="queued", points_read=0)
    stores.monitors.get_all_services.return_value = []
    async with connected(gateway) as client:
        tested = said(
            await client.call_tool(
                "test_design",
                {
                    "definition": starter()["definition"],
                    "bindings": {"value": "value"},
                    "dataset_id": "d1",
                },
            )
        )
        unknown = await client.call_tool(
            "test_design",
            {
                "definition": starter()["definition"],
                "bindings": {"value": "speed"},
                "dataset_id": "d1",
            },
        )
    assert tested["run_id"] == "run-1"
    assert stores.runs.create.await_args.args[0].bindings == {"value": "s1"}
    assert unknown.is_error and "speed" in said(unknown)
