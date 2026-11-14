"""What an agent can do here, as MCP tools.

A tool is a name, what it is for, its arguments and one or two calls to the
gateway's own routes. It adds no rule of its own: the route decides what the
key may do and answers in the API's words, and a tool that reshapes an answer
does so only to spare the agent what it already holds.
"""

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import FunctionType
from typing import Any, Literal
from urllib.parse import quote
from uuid import uuid4

import anyio
import httpx2
from off_key_core.schemas.pipeline_tools import ComponentSearchQuery, DesignEdit
from pydantic import BaseModel, ConfigDict, Field

INSTRUCTIONS = """\
You design anomaly monitors for the readings of this installation. A monitor \
runs a design: a graph of steps that leads from the input readings through \
preparation and a detector to calibration, a detection rule and the output.

A usual session:
0. get_access says what your key may do and whether a monitor has room to \
start now.
1. list_devices and list_readings show what can be monitored. profile_reading \
says what a reading looks like, which decides the steps it needs.
2. list_designs and get_design give a design to start from: a starter, a saved \
template or the design a running monitor uses.
3. search_components finds steps by purpose and get_component explains one \
with its settings. edit_design makes small changes and checks the result. Fix \
what its report lists before you go on.
4. test_design replays the design over recorded values of the readings, and \
get_test says how many alarms it would have raised.
5. propose_design hands the design to a member with your reason and the test. \
A member decides, and list_proposals shows the decision with their note. A key \
that may start monitors also has start_monitor. In shadow, a monitor records \
the alarms it would raise and alerts nobody.

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

    def schema(self) -> dict[str, Any]:
        return _without_titles(self.arguments.model_json_schema())


def _without_titles(schema: Any, names: bool = False) -> Any:
    """Pydantic titles every field after its name, which tells an agent nothing.

    ``names`` says the keys are names of properties, not words of the schema.
    """
    if isinstance(schema, list):
        return [_without_titles(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    return {
        key: _without_titles(value, not names and key in {"properties", "$defs"})
        for key, value in schema.items()
        if names or key != "title"
    }


TOOLS: dict[str, Tool] = {}


def tool(arguments: type[BaseModel], *, changes: bool = False, starts: bool = False):
    """Offer a function as a tool, named after it and described by its docstring.

    ``changes`` marks a tool that leaves something others see, ``starts`` one
    that only a key that may start monitors is offered.
    """

    def offer(call: FunctionType):
        described = " ".join((inspect.getdoc(call) or "").split())
        TOOLS[call.__name__] = Tool(
            call.__name__, described, arguments, call, changes, starts
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


@tool(Device)
async def list_readings(api: Api, args: Device):
    """The readings of one device with their label, unit and kind of value.
    A design monitors readings: its inputs are bound to reading ids."""
    return await api.get(f"/v1/devices/{_segment(args.device_id)}/readings")


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
                for key in ("id", "display_name", "reading_ids", "active")
            }
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
    return await api.post("/v1/pipelines/edit", _sent(args))


class Check(Args):
    definition: Design = Field(description=DESIGN)


@tool(Check)
async def validate_design(api: Api, args: Check):
    """Check a design you hold without changing it: whether it would run, the
    issues if not, and the features at every step. edit_design already checks
    what it returns, so use this for a design that came from elsewhere."""
    return await api.post("/v1/pipelines/validate", _sent(args))


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
            "The `dataset_id` of an earlier test. The design then runs on the "
            "same copy of the values, so the two results compare, and `days` "
            "is not used."
        ),
    )
    name: str = Field(
        default="Test by an agent",
        min_length=1,
        max_length=100,
        description="What the test is called in the Dojo, where members see it.",
    )


@tool(Test, changes=True)
async def test_design(api: Api, args: Test):
    """Replay a design over recorded values of its readings, as a monitor would
    have seen them. It copies the values into the Dojo and queues the run;
    follow it with get_test. Test before you propose or start a design, and
    test a changed design on the same `dataset_id`."""
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
    return {
        "run_id": run["id"],
        "dataset_id": dataset["id"],
        "status": run["status"],
        "points_total": run["points_total"],
        "start_at": dataset["start_at"],
        "end_at": dataset["end_at"],
    }


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
    results alarmed, how many separate alarms that makes per day, and against
    the labels of the dataset, where it has any, how many known problems the
    design caught and how late. `stats` says why observations gave no result.
    Call it again while the status is `queued` or `running`."""
    path = f"/v1/dojo/runs/{_segment(args.run_id)}"
    run = await _settled(
        lambda: api.get(path),
        lambda state: state["status"] not in {"queued", "running"},
        args.wait_seconds,
    )
    # The agent holds the design; the compiled copy of it is long.
    answer = {key: value for key, value in run.items() if key != "definition"}
    if run["status"] == "succeeded":
        metrics = answer["metrics"] = await api.get(f"{path}/metrics")
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
                answer["alarms"] = _episodes(alarmed.get("items", []))
            if not metrics.get("labels_total"):
                answer["note"] = (
                    "The dataset has no labels, so false_alarms counts every "
                    "separate alarm. alarm_count counts the results above the "
                    "boundary, several to one alarm. `alarms` lists when they were."
                )
    return answer


ALARM_RESULTS = 2000
ALARMS_LISTED = 20


def _episodes(results: list[dict]) -> dict[str, Any]:
    """Alarmed results in a row make one alarm: when it began and ended."""
    episodes: list[dict[str, Any]] = []
    previous = None
    for item in results:
        if previous is not None and item["sequence"] == previous + 1:
            episodes[-1]["end"] = item["timestamp"]
            episodes[-1]["results"] += 1
        else:
            episodes.append(
                {"start": item["timestamp"], "end": item["timestamp"], "results": 1}
            )
        previous = item["sequence"]
    return {
        "count": len(episodes),
        "listed": episodes[:ALARMS_LISTED],
        "complete": len(results) < ALARM_RESULTS,
    }


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
    reason: str = Field(
        min_length=1,
        description=(
            "Why this is worth running, for the member who decides: what it "
            "watches, what it would have caught and what it costs in alarms."
        ),
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
    it is tested, and say in the reason what the test showed."""
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
            "Any text of yours that names this start. Sent again, it answers "
            "with the same start instead of a second monitor, so send it when "
            "you repeat a call whose answer you did not get."
        ),
    )
    shadow: bool = Field(
        default=False,
        description=(
            "Start in shadow: the monitor learns and scores as any other, "
            "records each alarm it would raise as muted evidence and raises "
            "none. A key that may start in shadow only must set it."
        ),
    )


@tool(Start, changes=True, starts=True)
async def start_monitor(api: Api, args: Start):
    """Start a monitor that runs a design on its readings, without a member's
    decision. A live monitor raises alarms people act on, so start only a
    design you have tested, and propose instead where you are unsure. With
    `shadow` it alerts nobody: use that to see on live readings what a design
    would raise, then propose it with what you saw. A member takes a shadow
    monitor live. The answer is a start in progress; follow it with get_start.
    Replacing a running monitor stays with a member: propose that."""
    return await api.post(
        "/v1/pipelines/apply",
        {
            "display_name": args.name,
            "definition": args.definition,
            "bindings": args.bindings,
            "idempotency_key": args.idempotency_key or uuid4().hex,
            "shadow": args.shadow,
        }
        | ({"layout": args.layout} if args.layout else {}),
    )


class StartRef(Args):
    activation_id: str = Field(description="The `id` start_monitor answered with.")
    wait_seconds: int = WAIT


@tool(StartRef, starts=True)
async def get_start(api: Api, args: StartRef):
    """How a start stands: its `phase`, and once that is `succeeded` the
    monitor runs under `monitor_id`. `failed` comes with the `error` and the
    issues that stopped it."""
    path = f"/v1/pipeline-activations/{_segment(args.activation_id)}"
    return await _settled(
        lambda: api.get(path),
        lambda state: state["phase"] in {"succeeded", "failed", "cancelled"},
        args.wait_seconds,
    )
