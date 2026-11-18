"""What an agent can do here, as MCP tools.

A tool is a name, what it is for, its arguments and one or two calls to the
gateway's own routes. It adds no rule of its own: the route decides what the
key may do and answers in the API's words, and a tool that reshapes an answer
does so only to spare the agent what it already holds.
"""

import inspect
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import FunctionType
from typing import Any, Literal
from urllib.parse import quote
from uuid import uuid4

import anyio
import httpx2
from off_key_core.schemas.pipeline_tools import ComponentSearchQuery, DesignEdit
from off_key_core.schemas.pipelines import MonitorRationale
from pydantic import BaseModel, ConfigDict, Field

INSTRUCTIONS = """\
You design anomaly monitors for the readings of this installation. A monitor \
runs a design: a graph of steps that leads from the input readings through \
preparation and a detector to calibration, a detection rule and the output.

A usual session:
0. get_access says what your key may do and whether a monitor has room to \
start now.
1. list_devices and list_readings show what can be monitored. profile_reading \
says what a reading looks like, which decides the steps it needs, and \
get_values shows its values over a time range. A reading \
belongs to one monitor at a time: list_readings names the monitor that \
holds a reading, and a design bound to it cannot start.
2. list_designs and get_design give a design to start from: a starter, a saved \
template or the design a running monitor uses.
3. search_components finds steps by purpose and get_component explains one \
with its settings. edit_design makes small changes and checks the result. Fix \
what its report lists before you go on.
4. test_design replays the design over recorded values of the readings, and \
get_test says how many alarms it would have raised, with the scores around \
the first ones. Compare variants on the same `dataset_id`, so they replay the \
same values. To show that a design catches a problem the history lacks, pass \
`faults`: a step, drift, freeze or gap written into a copy, which get_test \
scores as caught or missed, with the delay.
5. propose_design hands the design to a member with your reason and the test. \
A member decides, and list_proposals shows the decision with their note. A key \
that may start monitors also has start_monitor. In shadow, a monitor records \
the alarms it would raise and alerts nobody.
6. list_monitors shows every monitor, with `mine` on those your key started, \
and get_monitor one with who started it and why. get_monitor_alarms lists \
the alarms it raised, or in shadow would have raised. Stop a shadow monitor of \
yours that is noisy or blind with stop_monitor, which frees its place, or \
propose it to run live with what it showed. Live monitors stay with members.
7. Clean up after yourself: list_my_tests shows the datasets and tests your \
key made, and delete_mine deletes those that have served, and your proposals \
once withdrawn or declined. Nothing else can be deleted with a key: not what \
members or other keys made, and no monitor, alarm or reading.

Each start carries a rationale for the members who read it next to the \
monitor: what it watches, why this design, the evidence and its limits, each \
one or two sentences of at most 200 characters, with numbers where you have \
them.

Warm-up: a design scores nothing until it has seen training_window_size plus \
calibration_window_size observations. These count observations, not time, so \
read the real cadence in profile_reading first: the starters assume a value \
every few seconds, and on a reading that reports every few minutes their \
windows outlast the recorded history. Shrink them to fit, or a test scores \
nothing.

A rule (a 0/1 flag from prepare.condition, scored by rule.score) alarms on \
policy.threshold: connect the detector straight to it, with no calibration \
step, and set value 1, so every 1 alarms from the first observation. A rule \
learns nothing, so the design has no warm-up. A rolling calibration such as \
calibrate.split, with policy.exceedance and several in a row, goes quiet on a \
fault that lasts.

A warning that observations "are skipped" means nothing is scored for them, \
such as a division by 0. When that case is the incident (zero messages from a \
broker), score it: write the case with if, or add a rule branch for it.

Pass a design between tools as you received it: keep `definition` and `layout` \
together, and let edit_design make a change instead of rewriting them by hand.\
"""


class ApiRefusal(Exception):
    """A route answered with an error; ``detail`` is what it said."""

    def __init__(self, status: int, detail: str, retry_after: str | None = None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.retry_after = retry_after


def _said(response: httpx2.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, list):
        # A refused request body: where each problem is and what it is.
        return "; ".join(
            f"{'.'.join(str(part) for part in item.get('loc', ())[1:])}: "
            f"{item.get('msg')}"
            for item in detail
        )
    return str(detail or response.text or response.reason_phrase)


def _answered(response: httpx2.Response) -> Any:
    """What a route answered, or its refusal."""
    if response.is_success:
        return response.json() if response.content else None
    raise ApiRefusal(
        response.status_code, _said(response), response.headers.get("retry-after")
    )


class Api:
    """The gateway's own routes, called as the caller of the MCP request."""

    def __init__(self, client: httpx2.AsyncClient, headers: dict[str, str]):
        self._client = client
        self._headers = headers

    async def get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return _answered(
            await self._client.get(path, params=params, headers=self._headers)
        )

    async def post(self, path: str, body: Mapping[str, Any] | None = None) -> Any:
        return _answered(
            await self._client.post(path, json=body, headers=self._headers)
        )

    async def delete(self, path: str) -> Any:
        return _answered(await self._client.delete(path, headers=self._headers))


def _segment(value: str) -> str:
    if value in {"", ".", ".."} or "/" in value or "\\" in value:
        raise ApiRefusal(422, f"{value!r} is not an id")
    return quote(value, safe="")


class Args(BaseModel):
    """What a tool is called with. A name the tool does not know is refused."""

    model_config = ConfigDict(extra="forbid")


def _sent(args: BaseModel) -> dict[str, Any]:
    """The arguments the caller gave, as a route takes them. An argument that
    was left out stays out, so the route's own default holds, and null at the
    top stands for left out."""
    sent = args.model_dump(mode="json", exclude_unset=True)
    return {key: value for key, value in sent.items() if value is not None}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    arguments: type[BaseModel]
    call: Callable[[Api, Any], Awaitable[Any]]
    changes: bool
    starts: bool
    deletes: bool

    def schema(self) -> dict[str, Any]:
        return _without_titles(self.arguments.model_json_schema())


def _without_titles(schema: Any, names: bool = False) -> Any:
    """Pydantic titles every field after its name, which tells an agent nothing,
    and maps a tagged union's tags beside its `oneOf`, whose `const` tags
    already say the same.

    ``names`` says the keys are names of properties, not words of the schema.
    """
    if isinstance(schema, list):
        return [_without_titles(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    return {
        key: _without_titles(value, not names and key in {"properties", "$defs"})
        for key, value in schema.items()
        if names or key not in {"title", "discriminator"}
    }


TOOLS: dict[str, Tool] = {}


def tool(
    arguments: type[BaseModel],
    *,
    changes: bool = False,
    starts: bool = False,
    deletes: bool = False,
):
    """Offer a function as a tool, named after it and described by its docstring.

    ``changes`` marks a tool that leaves something others see, ``starts`` one
    that only a key that may start monitors is offered, ``deletes`` one that
    removes for good what the key made.
    """

    def offer(call: FunctionType):
        described = " ".join((inspect.getdoc(call) or "").split())
        TOOLS[call.__name__] = Tool(
            call.__name__,
            described,
            arguments,
            call,
            changes or deletes,
            starts,
            deletes,
        )
        return call

    return offer


Design = dict[str, Any]
DESIGN = "The design, as get_design or edit_design returned its `definition`."
LAYOUT = "Its `layout` from the same answer, so that it opens well on the canvas."
BINDINGS = "The reading each input monitors: input slot id to reading id."


class Nothing(Args):
    pass


_MAY = {
    "nothing": (
        "propose: a member decides each design and starts it. start_monitor is "
        "not offered to this key."
    ),
    "shadow": (
        "propose, and start a monitor in shadow, where it records the alarms it "
        "would raise and alerts nobody."
    ),
    "live": "propose, and start a monitor in shadow or live.",
}


def _room(capacity: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not capacity:
        return None
    free = max(capacity["limit"] - capacity["running"], 0)
    return {**capacity, "free": free}


@tool(Nothing)
async def get_access(api: Api, args: Nothing):
    """What this key may do, how many monitors run against how many may, and
    how many proposals wait. Read it first: it says whether a design of yours
    can start now or only be proposed, and whether a member who accepts a
    proposal has room to start it."""
    agent = await api.get("/v1/agents/me")
    waiting = await api.get("/v1/pipeline-proposals", {"status": "open"})
    room = _room(waiting.get("capacity"))
    if room is not None:
        running = await api.get("/v1/monitors", {"active": True})
        shadow = sum(1 for item in running if item.get("shadow"))
        room |= {"live": len(running) - shadow, "shadow": shadow}
    answer = {
        "key": agent["name"],
        "starts": agent["starts"],
        "may": _MAY.get(agent["starts"], _MAY["nothing"]),
        "monitors": room,
        "open_proposals": len(waiting.get("items", [])),
    }
    if room is not None and room["free"] == 0:
        answer["note"] = (
            f"All {room['limit']} monitor places are taken. Nothing starts until "
            "a member stops a monitor or raises the limit, unless a design "
            "replaces a running monitor: propose it with replace_monitor_id."
        )
    return answer


class Devices(Args):
    active: bool | None = Field(
        default=None,
        description="true keeps the devices that send data now, false the others.",
    )


@tool(Devices)
async def list_devices(api: Api, args: Devices):
    """The devices of the installation, each with the ids of its readings and
    whether it sends data now. Start here to find what can be monitored."""
    return await api.get("/v1/devices", _sent(args))


class Device(Args):
    device_id: str = Field(description="Id of a device, as list_devices gives it.")


async def _holders(api: Api) -> dict[str, dict[str, Any]]:
    """The running monitor that holds each reading, by reading id."""
    monitors = await api.get("/v1/monitors", {"active": True})
    return {
        reading: {"id": item["id"], "name": item.get("display_name")}
        for item in monitors
        for reading in item.get("reading_ids") or ()
    }


@tool(Device)
async def list_readings(api: Api, args: Device):
    """The readings of one device with their label, unit and kind of value,
    and `held_by` the running monitor that watches a reading. A design monitors
    readings: its inputs are bound to reading ids, and a reading belongs to one
    monitor at a time."""
    readings = await api.get(f"/v1/devices/{_segment(args.device_id)}/readings")
    held = await _holders(api)
    return [
        item | ({"held_by": held[item["id"]]} if item.get("id") in held else {})
        for item in readings
    ]


class Profile(Args):
    reading_id: str
    days: int = Field(default=14, ge=1, le=90, description="How far back to look.")


@tool(Profile)
async def profile_reading(api: Api, args: Profile):
    """What a reading looked like over the last days: how often it reports and
    where it has gaps, how far its values reach, how much of its variation
    follows the hour of the day or the day of the week, and how far its level
    moved. Read it before you choose steps, and before you set how many
    observations a design learns from."""
    return await api.get(
        f"/v1/readings/{_segment(args.reading_id)}/profile", {"days": args.days}
    )


@tool(ComponentSearchQuery)
async def search_components(api: Api, args: ComponentSearchQuery):
    """Find steps by what they should do, a few lines each, the best fit first.
    Use it whenever a design needs a step you cannot name: a way to calm noise,
    to follow a daily rhythm, to combine readings, another detector."""
    return await api.get("/v1/pipeline-components/search", _sent(args))


class Component(Args):
    component_id: str = Field(
        description="Id of a component, as search_components gives it."
    )


@tool(Component)
async def get_component(api: Api, args: Component):
    """One step in full: what it does, when to use it, and every setting with
    its help, bounds and default. Read it before you add the step or change
    its settings."""
    return await api.get(f"/v1/pipeline-components/{_segment(args.component_id)}")


@tool(Nothing)
async def list_designs(api: Api, args: Nothing):
    """The designs to start from: the built-in starters, the templates members
    saved, and the monitors with the readings each watches. Read one with
    get_design."""
    catalog = await api.get("/v1/pipeline-components")
    saved = await api.get("/v1/pipelines", {"limit": 100})
    monitors = await api.get("/v1/monitors")
    return {
        "starters": [
            {"id": item["id"], "name": item["name"]} for item in catalog["templates"]
        ],
        "templates": [
            {key: item[key] for key in ("id", "name", "description")}
            for item in saved["items"]
        ],
        "monitors": [
            {
                key: item.get(key)
                for key in ("id", "display_name", "reading_ids", "active", "shadow")
            }
            | {"started_by": _started_by(item)}
            for item in monitors
        ],
    }


class DesignRef(Args):
    source: Literal["starter", "template", "monitor", "proposal"] = Field(
        description="Where the design is, as list_designs or list_proposals names it."
    )
    id: str


@tool(DesignRef)
async def get_design(api: Api, args: DesignRef):
    """One design with its `definition` and `layout`, and for a monitor or a
    proposal the `bindings` of its inputs to readings. Change it with
    edit_design."""
    key = _segment(args.id)
    if args.source == "starter":
        catalog = await api.get("/v1/pipeline-components")
        found = next((t for t in catalog["templates"] if t["id"] == args.id), None)
        if found is None:
            raise ApiRefusal(404, f"No starter is called {args.id!r}")
        return found
    if args.source == "template":
        saved = await api.get(f"/v1/pipelines/{key}")
        return {
            "name": saved["name"],
            "description": saved["description"],
            "definition": saved["draft"],
            "layout": saved["layout"],
        }
    if args.source == "proposal":
        return await api.get(f"/v1/pipeline-proposals/{key}")
    running = await api.get(f"/v1/monitors/{key}/pipeline")
    bound = ((running.get("run") or {}).get("binding_metadata") or {}).get("readings")
    return {
        "definition": running["definition"],
        "layout": running["layout"],
        "bindings": {item["slot_id"]: item["reading_id"] for item in bound or ()},
    }


class Edit(Args):
    definition: Design | None = Field(
        default=None, description=DESIGN + " Left out, the design starts empty."
    )
    layout: Design | None = Field(default=None, description=LAYOUT)
    edits: list[DesignEdit] = Field(
        min_length=1, max_length=100, description="The changes to make, in order."
    )


@tool(Edit)
async def edit_design(api: Api, args: Edit):
    """Change a design in small edits and check the result. Either every edit
    is made or none, and nothing is saved: the answer holds the changed
    `definition` and `layout`, the ids the edits `added`, and a `report` with
    the issues left. A design that would not run is no error, so read
    `report.issues` and fix them with further edits."""
    answer = await api.post("/v1/pipelines/edit", _sent(args))
    nodes = (answer.get("definition") or {}).get("nodes") or []
    answer["report"] = _compact(answer.get("report") or {}, nodes)
    if not any(node.get("kind") == "detector" for node in nodes):
        answer["note"] = STARTER_NOTE
    return answer


STARTER_NOTE = (
    "The design has no detector yet. A starter is quicker than building one: "
    "list_designs lists them and get_design with source 'starter' gives one."
)
# A step after the detector works on scores, so its features say nothing new.
SCORED = {"calibration", "policy", "output"}
# What a report says that an agent needs only where it differs.
QUIET = {
    "selected_node_id": None,
    "features_complete": True,
    "provenance_complete": True,
    "issues_truncated": False,
    "preparation_observations": 0,
    "ready_after": {},
}


def _compact(report: dict[str, Any], nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """The report without what the agent holds or what says nothing: the design
    it came with, the fingerprint, defaults, and features after the detector."""
    scored = {node.get("id") for node in nodes if node.get("kind") in SCORED}
    compact = {
        key: value
        for key, value in report.items()
        if key not in {"definition", "definition_omitted", "fingerprint"}
        and (key not in QUIET or value != QUIET[key])
    }
    if "features" in compact:
        compact["features"] = {
            step: [
                {key: value for key, value in item.items() if value not in (None, [])}
                for item in columns
            ]
            for step, columns in compact["features"].items()
            if step not in scored
        }
    return compact


class Check(Args):
    definition: Design = Field(description=DESIGN)


@tool(Check)
async def validate_design(api: Api, args: Check):
    """Check a design you hold without changing it: whether it would run, the
    issues if not, and the features at every step. edit_design already checks
    what it returns, so use this for a design that came from elsewhere."""
    report = await api.post("/v1/pipelines/validate", _sent(args))
    return _compact(report, args.definition.get("nodes") or [])


class InjectedFault(Args):
    kind: Literal["step", "drift", "freeze", "gap"]
    reading: str
    start: datetime
    end: datetime
    size: float | None = Field(
        default=None, description="In the reading's unit; default 3 sigma."
    )


class Test(Args):
    definition: Design = Field(description=DESIGN)
    bindings: dict[str, str] = Field(min_length=1, description=BINDINGS)
    days: int = Field(
        default=7,
        ge=1,
        le=30,
        description="How many days of recorded values to replay, up to now.",
    )
    dataset_id: str | None = Field(
        default=None,
        description=(
            "An earlier test's `dataset_id`, to replay the same values so the "
            "results compare. `days` is then not used."
        ),
    )
    name: str = Field(
        default="Test by an agent",
        min_length=1,
        max_length=100,
        description="Its name in the Dojo, where members see it.",
    )
    faults: list[InjectedFault] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Written into a labelled copy after warm-up, not overlapping: "
            "step adds size, drift ramps to it, freeze holds a value, "
            "gap drops values."
        ),
    )


@tool(Test, changes=True)
async def test_design(api: Api, args: Test):
    """Replay a design over recorded values of its readings, as a monitor would
    have seen them, in the Dojo; follow it with get_test. `notes` say how much
    of the replay the warm-up takes and whether a running monitor holds a bound
    reading. Test before you propose or start, and test a changed design on
    the same `dataset_id`, which with `faults` is the copy holding them."""
    if args.dataset_id:
        dataset = await api.get(f"/v1/dojo/datasets/{_segment(args.dataset_id)}")
    else:
        now = datetime.now(UTC)
        dataset = await api.post(
            "/v1/dojo/datasets/history",
            {
                "name": f"{args.name} · last {args.days} days",
                "reading_ids": sorted(set(args.bindings.values())),
                "start": (now - timedelta(days=args.days)).isoformat(),
                "end": now.isoformat(),
            },
        )
    series = {item["reading_id"]: item["id"] for item in dataset["series"]}
    missing = sorted(set(args.bindings.values()) - series.keys())
    if missing:
        raise ApiRefusal(422, f"The dataset holds no values of {', '.join(missing)}")
    if args.faults:
        dataset = await _with_faults(api, dataset, series, args)
        series = {item["reading_id"]: item["id"] for item in dataset["series"]}
    run = await api.post(
        "/v1/dojo/runs",
        {
            "dataset_id": dataset["id"],
            "name": args.name,
            "definition": args.definition,
            "bindings": {
                slot: series[reading] for slot, reading in args.bindings.items()
            },
        },
    )
    answer = {
        "run_id": run["id"],
        "dataset_id": dataset["id"],
        "status": run["status"],
        "points_total": run["points_total"],
        "start_at": dataset["start_at"],
        "end_at": dataset["end_at"],
    }
    notes = [
        _warm_up(args.definition, dataset, run["points_total"], len(args.bindings))
    ]
    try:
        held = await _holders(api)
    except ApiRefusal:
        held = {}
    taken = sorted(
        f"{reading} (monitor {held[reading]['id']})"
        for reading in set(args.bindings.values())
        if reading in held
    )
    if taken:
        notes.append(
            "A running monitor already holds "
            + ", ".join(taken)
            + ", so this design cannot start on it. Test it all the same, then "
            "bind other readings or propose it to replace that monitor."
        )
    if notes := [note for note in notes if note]:
        answer["notes"] = notes
    return answer


async def _with_faults(api: Api, dataset: dict, series: dict, args: Test) -> dict:
    """A copy of the dataset with the faults written in and labelled."""
    unknown = sorted({item.reading for item in args.faults} - series.keys())
    if unknown:
        raise ApiRefusal(
            422, f"Faults name readings the test does not bind: {', '.join(unknown)}"
        )
    return await api.post(
        f"/v1/dojo/datasets/{_segment(dataset['id'])}/faults",
        {
            "name": f"{args.name} · {len(args.faults)} injected "
            + ("fault" if len(args.faults) == 1 else "faults"),
            "faults": [
                {
                    "kind": item.kind,
                    "series_id": series[item.reading],
                    "start_at": item.start.isoformat(),
                    "end_at": item.end.isoformat(),
                    **({} if item.size is None else {"size": item.size}),
                }
                for item in args.faults
            ],
        },
    )


def _warm_up(definition: Design, dataset: dict, points: int, inputs: int) -> str:
    """How much of a replay the warm-up takes, said before the test runs."""
    settings = definition.get("settings") or {}
    detectors = [
        node.get("component")
        for node in definition.get("nodes") or []
        if node.get("kind") == "detector"
    ]
    # Rules learn nothing, so a design of rules alone only calibrates.
    rules_only = bool(detectors) and all(item == "rule.score" for item in detectors)
    windows = (
        ("calibration_window_size",)
        if rules_only
        else (
            "training_window_size",
            "calibration_window_size",
        )
    )
    warm_up = sum(settings.get(key) or 0 for key in windows)
    observations = points // max(inputs, 1)
    if not warm_up or not observations:
        return ""
    if warm_up >= observations:
        return (
            f"The replay holds about {observations} observations, fewer than "
            f"the warm-up of {warm_up}, so nothing will be scored. Test more "
            "days or shrink training_window_size and calibration_window_size."
        )
    try:
        start = datetime.fromisoformat(dataset["start_at"])
        end = datetime.fromisoformat(dataset["end_at"])
    except (KeyError, TypeError, ValueError):
        return ""
    share = warm_up / observations
    scored_from = (start + (end - start) * share).isoformat()
    return (
        f"Warm-up takes {warm_up} of about {observations} observations "
        f"({share:.0%}), so scoring starts near {scored_from}."
    )


async def _settled(read: Callable[[], Awaitable[dict]], done, wait: int) -> dict:
    """Read until ``done`` says so or the wait is over, so an agent asks seldom."""
    last = anyio.current_time() + wait - PAUSE
    # What is read lives in another service, which offers no event to wait on.
    while not done(state := await read()) and anyio.current_time() <= last:  # noqa: ASYNC110
        await anyio.sleep(PAUSE)
    return state


PAUSE = 3.0
WAIT = Field(
    default=20,
    ge=0,
    le=45,
    description="How many seconds to wait for it to finish before answering.",
)


class TestRef(Args):
    run_id: str = Field(description="The `run_id` test_design answered with.")
    wait_seconds: int = WAIT


@tool(TestRef)
async def get_test(api: Api, args: TestRef):
    """How a test stands and, once it has `succeeded`, what it found: how many
    results alarmed, how many separate alarms per day, and against the
    dataset's labels (injected faults among them) how many it caught and how
    late. `alarms.excerpts` holds the score and threshold around the first
    alarms; read the input values then with get_values. `stats` says why
    observations gave no result. Call it again while `queued` or `running`."""
    path = f"/v1/dojo/runs/{_segment(args.run_id)}"
    run = await _settled(
        lambda: api.get(path),
        lambda state: state["status"] not in {"queued", "running"},
        args.wait_seconds,
    )
    # The agent holds the design; the compiled copy of it is long.
    answer = _results_are(_renamed(run, {"id": "run_id", "alarm_count": ALARMING}))
    del answer["definition"]
    # A key is no member: the run names the agent instead.
    if agent := answer.pop("created_by_agent", None):
        answer["created_by"] = f"Agent · {agent}"
    if meanings := {
        key: STATS[key] for key in answer.get("stats") or {} if key in STATS
    }:
        answer["stats_meaning"] = meanings
    if run["status"] == "succeeded":
        metrics = await api.get(f"{path}/metrics")
        metrics = answer["metrics"] = _results_are(
            _renamed(metrics, {"alarm_count": ALARMING})
        )
        answer["alarms"] = {"count": 0, "listed": [], "complete": True}
        if metrics.get("scored_from") is None:
            answer["note"] = _unscored(run)
        elif run.get("alarm_count"):
            try:
                alarmed = await api.get(
                    f"{path}/results", {"alarm": "true", "limit": ALARM_RESULTS}
                )
            except ApiRefusal:
                alarmed = None
            if alarmed is not None:
                answer["alarms"], around = _episodes(alarmed.get("items", []))
                with suppress(ApiRefusal):
                    answer["alarms"]["excerpts"] = {
                        "columns": ["time", "score", "threshold", "alarm"],
                        "around": [
                            {
                                "start": item["start"],
                                "rows": await _excerpt(api, path, item),
                            }
                            for item in around
                        ],
                    }
            if not metrics.get("labels_total"):
                answer["note"] = (
                    "The dataset has no labels, so false_alarms counts every "
                    "separate alarm. alarming_results counts the results above "
                    "the boundary, several to one alarm. `alarms` lists when "
                    "they were."
                )
    return answer


ALARM_RESULTS = 2000
ALARMS_LISTED = 20
# Several results in a row make one alarm, so the count of results says so.
ALARMING = "alarming_results"
# What each reason a replayed value gave no result stands for.
STATS = {
    "missing_reading": "no value of another bound reading had arrived yet",
    "waiting_for_reading": (
        "held until the other readings' next values arrived; usual with "
        "several readings, as each observation takes one value of each"
    ),
    "stale_reading": "another reading's latest value was too old to pair with",
    "pipeline_observation_rejected": (
        "a step skipped it, such as a division by 0 or a gate that held it back"
    ),
    "observation_too_old": "it was already older than its reading's limit on arrival",
}


def _renamed(item: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    return {names.get(key, key): value for key, value in item.items()}


# A run's `strategy` names what its results are, not the starter it came from.
RESULTS_ARE = {
    "adaptive_stream": "scores against a threshold",
    "static_baseline": "p-values of a conformal martingale",
}


def _results_are(item: dict[str, Any]) -> dict[str, Any]:
    if "strategy" not in item:
        return item
    strategy = item.pop("strategy")
    return item | {"results_are": RESULTS_ARE.get(strategy, strategy)}


def _runs(results: list[dict], sequence: str, timestamp: str) -> list[dict]:
    """Alarmed results in a row make one alarm: when it began and ended, and
    the sequences it spans."""
    episodes: list[dict[str, Any]] = []
    for item in results:
        if episodes and item[sequence] == episodes[-1]["last"] + 1:
            episodes[-1] |= {"end": item[timestamp], "last": item[sequence]}
            episodes[-1]["results"] += 1
        else:
            episodes.append(
                {
                    "start": item[timestamp],
                    "end": item[timestamp],
                    "results": 1,
                    "first": item[sequence],
                    "last": item[sequence],
                }
            )
    return episodes


def _public(episode: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in episode.items() if key not in SEQUENCES}


SEQUENCES = {"first", "last"}


def _episodes(results: list[dict]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The alarms of a test as an agent reads them, and the first few with
    the sequences they span, to read around."""
    episodes = _runs(results, "sequence", "timestamp")
    return {
        "count": len(episodes),
        "listed": [_public(item) for item in episodes[:ALARMS_LISTED]],
        "complete": len(results) < ALARM_RESULTS,
    }, episodes[:EXCERPTS]


EXCERPTS = 5
AROUND = 6
EXCERPT_RESULTS = 60


async def _excerpt(api: Api, path: str, episode: dict[str, Any]) -> list[list]:
    """The results from a few before an alarm to a few after it, as rows of
    time, score, threshold and alarm."""
    first = max(episode["first"] - AROUND, 0)
    span = episode["last"] + AROUND - first + 1
    query: dict[str, Any] = {"limit": min(span, EXCERPT_RESULTS)}
    if first > 0:
        query["after"] = first - 1
    page = await api.get(f"{path}/results", query)
    return [
        [item["timestamp"], item["score"], item["threshold"], item["alarm"]]
        for item in page.get("items", [])
    ]


def _unscored(run: dict) -> str:
    """Zero alarms reads as a good design; say when it only means no scores."""
    settings = (run.get("definition") or {}).get("settings") or {}
    warm_up = sum(
        settings.get(key) or 0
        for key in ("training_window_size", "calibration_window_size")
    )
    needed = f" its warm-up of {warm_up} observations" if warm_up else " its warm-up"
    return (
        f"Nothing was scored: the replay gave {run.get('result_count', 0)} "
        f"observations, which{needed} used up. The alarm count says nothing "
        "about the design yet. Test more days once they are recorded, or "
        "shorten training_window_size and calibration_window_size to try it."
    )


class Proposal(Args):
    name: str = Field(
        min_length=1, max_length=120, description="The name the monitor would carry."
    )
    rationale: MonitorRationale = Field(
        description="Why it is worth running: one or two sentences per field."
    )
    reason: str | None = Field(
        default=None,
        description="Anything the four fields leave out. Usually not needed.",
    )
    definition: Design = Field(description=DESIGN)
    layout: Design | None = Field(default=None, description=LAYOUT)
    bindings: dict[str, str] = Field(min_length=1, description=BINDINGS)
    test_run_id: str | None = Field(
        default=None,
        description=(
            "The `run_id` of the test that supports it: one that succeeded, on "
            "this very design. Test again after any change but a title."
        ),
    )
    replace_monitor_id: str | None = Field(
        default=None,
        description="A running monitor the design is meant to take the place of.",
    )


@tool(Proposal, changes=True)
async def propose_design(api: Api, args: Proposal):
    """Hand a design to a member to decide on. This is how a design of yours
    comes to run: a member opens it on the canvas, reads your reason and
    starts or declines it. The design must check without errors. Propose once
    it is tested, and say in the rationale's evidence what the test showed."""
    made = await api.post("/v1/pipeline-proposals", _sent(args))
    if args.replace_monitor_id is None:
        try:
            waiting = await api.get("/v1/pipeline-proposals", {"status": "open"})
        except ApiRefusal:
            # The proposal is made; a hint that cannot be read must not hide it.
            return made
        room = _room(waiting.get("capacity"))
        if room is not None and room["free"] == 0:
            made["note"] = (
                f"All {room['limit']} monitor places are taken, so a member who "
                "accepts this cannot start it until a monitor stops or the limit "
                "is raised. Say so in your report to them."
            )
    return made


class Proposals(Args):
    status: Literal["open", "accepted", "declined", "withdrawn"] | None = Field(
        default=None, description="Only proposals in this state."
    )


@tool(Proposals)
async def list_proposals(api: Api, args: Proposals):
    """The proposals, the newest first, without their designs: who made each,
    whether it still waits, and for a decided one who decided and their
    `decision_note`. Read it to learn what became of your proposals and why one
    was declined."""
    return await api.get("/v1/pipeline-proposals", _sent(args))


class ProposalRef(Args):
    proposal_id: str


@tool(ProposalRef, changes=True)
async def withdraw_proposal(api: Api, args: ProposalRef):
    """Take back a proposal of yours that still waits, for example before you
    propose a better design in its place."""
    return await api.post(
        f"/v1/pipeline-proposals/{_segment(args.proposal_id)}/withdraw"
    )


class Mine(Args):
    run_id: str | None = None
    dataset_id: str | None = None
    proposal_id: str | None = None


@tool(Nothing)
async def list_my_tests(api: Api, args: Nothing):
    """The datasets and tests your key made, the newest first."""
    datasets = await api.get("/v1/dojo/datasets", {"mine": "true", "limit": 100})
    runs = await api.get("/v1/dojo/runs", {"mine": "true", "limit": 100})
    return {
        "datasets": [
            {key: item[key] for key in ("id", "name", "created_at")}
            for item in datasets["items"]
        ],
        "tests": [
            {
                "run_id": item["id"],
                "dataset_id": item["dataset_id"],
                "name": item["name"],
                "status": item["status"],
                "created_at": item["created_at"],
            }
            for item in runs["items"]
        ],
        "more": bool(datasets.get("next_offset") or runs.get("next_offset")),
    }


@tool(Mine, deletes=True)
async def delete_mine(api: Api, args: Mine):
    """Delete one thing your key made: a test, cancelled first if it runs; a
    dataset with only your tests on it; or a proposal once withdrawn or
    declined. A test a proposal or monitor names as evidence stays."""
    named = {key: value for key, value in _sent(args).items() if isinstance(value, str)}
    if len(named) != 1:
        raise ApiRefusal(422, "Name one of run_id, dataset_id or proposal_id")
    if args.proposal_id is not None:
        await api.delete(f"/v1/pipeline-proposals/{_segment(args.proposal_id)}")
    elif args.dataset_id is not None:
        runs = await api.get(
            "/v1/dojo/runs",
            {"dataset_id": args.dataset_id, "mine": "true", "limit": 100},
        )
        for item in runs["items"]:
            await _ended(api, item)
        await api.delete(f"/v1/dojo/datasets/{_segment(args.dataset_id)}")
    elif args.run_id is not None:
        path = f"/v1/dojo/runs/{_segment(args.run_id)}"
        await _ended(api, await api.get(path))
        await api.delete(path)
    return {"deleted": named}


async def _ended(api: Api, run: dict[str, Any]) -> None:
    """Cancel a run that still waits or runs, and wait for its end."""
    if run["status"] not in ACTIVE_RUN:
        return
    path = f"/v1/dojo/runs/{_segment(run['id'])}"
    await api.post(f"{path}/cancel")
    run = await _settled(
        lambda: api.get(path),
        lambda state: state["status"] not in ACTIVE_RUN,
        CANCEL_WAIT,
    )
    if run["status"] in ACTIVE_RUN:
        raise ApiRefusal(
            409,
            f"Test {run['id']} is cancelled and still ending; call delete_mine "
            "again in a few seconds.",
        )


ACTIVE_RUN = {"queued", "running"}
# A running replay ends at the worker's next beat, within seconds.
CANCEL_WAIT = 30


def _started_by(monitor: Mapping[str, Any]) -> dict[str, Any] | None:
    origin = monitor.get("origin")
    if not origin:
        return None
    return {"author": origin["author"], "kind": origin["author_kind"]}


async def _me(api: Api) -> str:
    return (await api.get("/v1/agents/me"))["name"]


def _mine(monitor: Mapping[str, Any], me: str) -> bool:
    origin = monitor.get("origin") or {}
    return origin.get("author_kind") == "agent" and origin.get("author") == me


class Monitors(Args):
    active: bool | None = Field(
        default=None,
        description="true keeps the monitors that run, false the stopped ones.",
    )
    mine: bool = Field(
        default=False, description="true keeps the monitors your key started."
    )


@tool(Monitors)
async def list_monitors(api: Api, args: Monitors):
    """The monitors, each with its name, whether it runs and in shadow, the
    readings it holds, when it started, who started it, and `mine` where your
    key did. Read it to find your monitors and to see which readings are
    taken: a reading belongs to one monitor at a time."""
    params = {"active": args.active} if args.active is not None else None
    monitors = await api.get("/v1/monitors", params)
    me = await _me(api)
    listed = [
        {
            "id": item["id"],
            "name": item.get("display_name"),
            "active": item.get("active"),
            "shadow": item.get("shadow", False),
            "reading_ids": item.get("reading_ids", []),
            "started_at": item.get("created_at"),
            "started_by": _started_by(item),
            "mine": _mine(item, me),
        }
        for item in monitors
    ]
    return [item for item in listed if item["mine"] or not args.mine]


class MonitorRef(Args):
    monitor_id: str = Field(
        description="Id of a monitor, as list_monitors or get_start gives it."
    )


@tool(MonitorRef)
async def get_monitor(api: Api, args: MonitorRef):
    """One monitor: whether it runs and in shadow, its readings and how it is
    doing, who started it, the rationale they gave, the test behind it, and
    every start and stop since. Read its design with get_design."""
    monitor = await api.get(f"/v1/monitors/{_segment(args.monitor_id)}")
    origin = monitor.get("origin")
    return {
        "id": monitor["id"],
        "name": monitor.get("display_name"),
        "active": monitor.get("active"),
        "shadow": monitor.get("shadow", False),
        "reading_ids": monitor.get("reading_ids", []),
        "started_at": monitor.get("created_at"),
        "status": monitor.get("operational_status") or {},
        "mine": _mine(monitor, await _me(api)),
        "origin": origin,
    }


class Values(Args):
    reading_id: str
    start: datetime = Field(description="From when, as an ISO 8601 time.")
    end: datetime | None = Field(default=None, description="Until when; now if out.")
    points: int = Field(
        default=200,
        ge=10,
        le=500,
        description="At most this many rows; a long range is summed up in stretches.",
    )


@tool(Values)
async def get_values(api: Api, args: Values):
    """Recorded values of one reading over a time range, to look at what a
    profile, a test or an alarm points at. A short range answers with every
    value; a longer one with the mean, lowest and highest value and count of
    each stretch, so a spike survives."""
    query = {
        "start": args.start.isoformat(),
        "buckets": args.points,
        "view": "auto",
    } | ({"end": args.end.isoformat()} if args.end else {})
    history = await api.get(
        f"/v1/readings/{_segment(args.reading_id)}/measurements/buckets", query
    )
    points = history.get("points", [])
    if history.get("representation") == "mean":
        columns = ["time", "mean", "min", "max", "count"]
        rows = [
            [
                item["timestamp"],
                item["value"],
                item.get("minimum"),
                item.get("maximum"),
                item.get("count"),
            ]
            for item in points
        ]
    else:
        columns = ["time", "value"]
        rows = [[item["timestamp"], item["value"]] for item in points]
    answer: dict[str, Any] = {
        "reading_id": args.reading_id,
        "columns": columns,
        "rows": rows,
    }
    if history.get("interval_ms"):
        answer["stretch_seconds"] = history["interval_ms"] / 1000
    if history.get("column_ms"):
        answer["note"] = (
            "More values than rows: each stretch keeps its first, last, lowest "
            "and highest value. Narrow the range to see every value."
        )
    return answer


def _score(row: Mapping[str, Any]) -> float:
    return row.get("anomaly_score") or 0.0


class MonitorAlarms(Args):
    monitor_id: str = Field(description="Id of a monitor, as list_monitors gives it.")
    limit: int = Field(
        default=500,
        ge=1,
        le=2000,
        description="How many of the newest alarmed observations to read.",
    )


@tool(MonitorAlarms)
async def get_monitor_alarms(api: Api, args: MonitorAlarms):
    """The alarms a running monitor raised, or in shadow would have raised, in
    the shape of a test's: when each began and ended, how many results it
    spans, and its highest score against the threshold, the newest last.
    `muted` says it alerted nobody. Read the values around one with
    get_values, and compare the count per day with the test behind the
    monitor."""
    monitor_id = _segment(args.monitor_id)
    monitor = await api.get(f"/v1/monitors/{monitor_id}")
    readings = monitor.get("reading_ids") or []
    if not readings:
        raise ApiRefusal(409, "The monitor watches no reading the catalogue still has.")
    rows = await api.get(
        "/v1/evidence/chart",
        {
            "reading_id": readings,
            "monitor_id": args.monitor_id,
            "alarm": "true",
            "limit": args.limit,
        },
    )
    episodes = _runs(rows, "sequence_number", "timestamp")
    owner = {
        sequence: episode["first"]
        for episode in episodes
        for sequence in range(episode["first"], episode["last"] + 1)
    }
    peaks: dict[int, dict] = {}
    for item in rows:
        first = owner[item["sequence_number"]]
        if first not in peaks or _score(item) > _score(peaks[first]):
            peaks[first] = item
    listed = []
    for episode in episodes[-ALARMS_LISTED:]:
        peak = peaks[episode["first"]]
        listed.append(
            _public(episode)
            | {
                "score": peak.get("anomaly_score"),
                "threshold": peak.get("threshold"),
                "muted": peak.get("muted", False),
            }
        )
    answer = {
        "monitor_id": args.monitor_id,
        "shadow": monitor.get("shadow", False),
        "running_since": monitor.get("created_at"),
        "count": len(episodes),
        "listed": listed,
        "complete": len(rows) < args.limit,
    }
    if not episodes:
        answer["note"] = (
            "No alarm yet. get_monitor says whether it scores already or is "
            "still learning."
        )
    return answer


class Start(Args):
    name: str = Field(
        min_length=1, max_length=120, description="The name the monitor carries."
    )
    definition: Design = Field(description=DESIGN)
    layout: Design | None = Field(default=None, description=LAYOUT)
    bindings: dict[str, str] = Field(min_length=1, description=BINDINGS)
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description=(
            "Any text naming this start. Sent again, it answers with the same "
            "start, not a second monitor: use it to repeat a call whose answer "
            "you missed."
        ),
    )
    shadow: bool = Field(
        default=False,
        description=(
            "Start in shadow: it scores as any other and records the alarms it "
            "would raise as muted evidence, raising none. A key limited to "
            "shadow must set it."
        ),
    )
    rationale: MonitorRationale = Field(
        description="Why it runs, for members: one or two sentences per field."
    )
    test_run_id: str | None = Field(
        default=None,
        description=(
            "The `run_id` of the test that supports it: one that succeeded, on "
            "this very design. It stays with the monitor as its evidence."
        ),
    )


@tool(Start, changes=True, starts=True)
async def start_monitor(api: Api, args: Start):
    """Start a monitor that runs a design on its readings, without a member's
    decision. A live monitor raises alarms people act on, so start only a
    design you have tested, and propose instead where you are unsure. With
    `shadow` it alerts nobody: use that to see on live readings what a design
    would raise, then propose it with what you saw. A member takes a shadow
    monitor live. The answer is a start in progress; follow it with get_start,
    and use its `monitor_id` with get_monitor and stop_monitor. Replacing a
    running monitor stays with a member: propose that."""
    started = await api.post(
        "/v1/pipelines/apply",
        {
            "display_name": args.name,
            "definition": args.definition,
            "bindings": args.bindings,
            "idempotency_key": args.idempotency_key or uuid4().hex,
            "shadow": args.shadow,
            "rationale": args.rationale.model_dump(mode="json"),
        }
        | ({"layout": args.layout} if args.layout else {})
        | ({"test_run_id": args.test_run_id} if args.test_run_id else {}),
    )
    return _start(started)


def _start(activation: dict[str, Any]) -> dict[str, Any]:
    """A start without the id of its run inside the monitor, which no tool
    reads and which agents took for a test's `run_id`."""
    return {key: value for key, value in activation.items() if key != "run_id"}


class StartRef(Args):
    activation_id: str = Field(description="The `id` start_monitor answered with.")
    wait_seconds: int = WAIT


@tool(StartRef, starts=True)
async def get_start(api: Api, args: StartRef):
    """How a start stands: its `phase`, and once that is `succeeded` the
    monitor runs under `monitor_id`. `failed` comes with the `error` and the
    issues that stopped it."""
    path = f"/v1/pipeline-activations/{_segment(args.activation_id)}"
    return _start(
        await _settled(
            lambda: api.get(path),
            lambda state: state["phase"] in {"succeeded", "failed", "cancelled"},
            args.wait_seconds,
        )
    )


class Stop(Args):
    monitor_id: str = Field(description="Id of a shadow monitor your key started.")
    note: str = Field(
        min_length=1,
        max_length=200,
        description=(
            "Why it stops, in one or two sentences, for the members who read "
            "its history: noisy, blind, or replaced by a better design."
        ),
    )


@tool(Stop, changes=True, starts=True)
async def stop_monitor(api: Api, args: Stop):
    """Stop a shadow monitor your key started, for example one that is noisy
    or blind, and free its place and readings. Its records stay. A live
    monitor, or one somebody else started, stays with members: propose that
    instead."""
    return await api.post(
        f"/v1/monitors/{_segment(args.monitor_id)}/stop", {"note": args.note}
    )
