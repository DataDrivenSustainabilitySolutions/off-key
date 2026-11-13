"""Versioned monitoring designs; safe to import in the control plane."""

from datetime import datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    WrapSerializer,
    field_validator,
    model_serializer,
    model_validator,
)

from off_key_core.utils.json_budget import fits_json_budget

from .collection_policy import CollectionPolicy
from .forecast import ForecastModelInfo
from .pipeline_versions import (
    Learning,
    Strategy,
    derived_strategy,
    downgrade,
    editor_form,
    upgrade,
)
from .public_names import public

# The one monitoring-strategy vocabulary; forms, pipelines and RADAR share it.
PipelineStrategy = Strategy
DEFAULT_TRAINING_WINDOW_SIZE = 1200
DEFAULT_CALIBRATION_WINDOW_SIZE = 360
NodeKind = Literal[
    "source", "transform", "merge", "detector", "calibration", "policy", "output"
]
# Errors block applying a design; warnings are shown and do not.
IssueSeverity = Literal["error", "warning"]
PortType = Literal[
    "features", "scores", "forecasts", "p_values", "decisions", "evidence"
]
# Where a step sits in the composer's menus: what it does for the operator, which
# its kind alone does not say. Every transform prepares, combines, normalizes,
# reduces or routes features, and a forecaster is a detector that forecasts.
StepGroup = Literal[
    "input",
    "prepare",
    "combine",
    "normalize",
    "reduce",
    "route",
    "forecaster",
    "detector",
    "calibration",
    "policy",
    "output",
]
MAX_PIPELINE_EXECUTION_BYTES = 96 * 1024
# Detectors that can feed one policy, and how the policy combines them.
MAX_DETECTORS = 4
FusionMode = Literal["max", "mean"]
# A block is a short chain of steps; the library lists every block at once.
MAX_BLOCKS = 100
MAX_BLOCK_STEPS = 16
MAX_BLOCK_BYTES = 16 * 1024


class PipelineModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class InputSlot(PipelineModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=120)
    unit: str | None = Field(default=None, max_length=32)


class PipelineNode(PipelineModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    kind: NodeKind
    component: str = Field(min_length=1, max_length=160)
    contract_version: int = Field(default=1, ge=1)
    params: dict[str, Any] = Field(default_factory=dict)
    label: str | None = Field(default=None, max_length=120)


class PipelineEdge(PipelineModel):
    source: str
    target: str
    # Explicit order is executable; visual positions have no processing meaning.
    order: int = Field(default=0, ge=0, le=127)


class PipelineSettings(PipelineModel):
    training_window_size: int = Field(
        default=DEFAULT_TRAINING_WINDOW_SIZE, ge=2, le=1_000_000
    )
    calibration_window_size: int = Field(
        default=DEFAULT_CALIBRATION_WINDOW_SIZE, ge=1, le=1_000_000
    )
    seed: int | None = 42
    conformal_strategy: Literal["split"] = "split"


class PipelineDefinition(PipelineModel):
    """A monitoring design; held as schema 2, written as schema 1 when it can be.

    A design has no lane of its own: how it runs follows from how its steps
    learn. ``strategy`` is read from schema 1 designs and then dropped. The
    schema 1 form that is written carries the lane the steps share, which is
    what a schema 1 design stored, so stored designs and fingerprints stay as
    they were.
    """

    schema_version: Literal[1, 2] = 1
    strategy: PipelineStrategy | None = None
    input_slots: list[InputSlot] = Field(default_factory=list, max_length=100)
    # Drafts intentionally allow incomplete/disconnected graphs. The limits
    # count the calibration step and its connection into the policy, which
    # schema 1 designs did not have: 64 nodes and 128 edges of their own.
    nodes: list[PipelineNode] = Field(default_factory=list, max_length=65)
    edges: list[PipelineEdge] = Field(default_factory=list, max_length=129)
    settings: PipelineSettings = Field(default_factory=PipelineSettings)

    @model_validator(mode="after")
    def upgrade_schema_1(self) -> "PipelineDefinition":
        """Read a schema 1 design as schema 2, after its own limits held."""
        if self.schema_version == 1:
            if len(self.nodes) > 64:
                raise ValueError("A schema 1 design has at most 64 nodes")
            if len(self.edges) > 128:
                raise ValueError("A schema 1 design has at most 128 edges")
            data = upgrade(
                {"schema_version": 1, "nodes": self.nodes, "edges": self.edges}
            )
            self.schema_version = 2
            self.nodes = [PipelineNode.model_validate(item) for item in data["nodes"]]
            self.edges = [PipelineEdge.model_validate(item) for item in data["edges"]]
        self.strategy = None
        return self

    @property
    def lane(self) -> PipelineStrategy | None:
        """The lane all the design's learned steps share, if they share one."""
        return derived_strategy([node.model_dump() for node in self.nodes])

    @model_serializer(mode="wrap")
    def schema_1_when_possible(self, handler, info):
        data = downgrade(handler(self))
        if info.exclude_defaults and data.get("schema_version") == 1:
            # Schema 1's own defaults, as a schema 1 design always left them out.
            data.pop("schema_version")
            if data.get("strategy") == "static_baseline":
                data.pop("strategy")
        return data


def _editor_form(definition: "PipelineDefinition", handler):
    return editor_form(handler(definition))


# A design in a response the editor reads: always schema 2, with its
# calibration step and without a lane.
EditorDefinition = Annotated[PipelineDefinition, WrapSerializer(_editor_form)]


class CanvasPosition(PipelineModel):
    x: float
    y: float
    label: str | None = Field(default=None, max_length=120)


class CanvasViewport(CanvasPosition):
    zoom: float = Field(default=1, gt=0, le=10)


class PipelineLayout(PipelineModel):
    schema_version: Literal[1] = 1
    version: int = Field(default=1, ge=1)
    nodes: dict[str, CanvasPosition] = Field(default_factory=dict)
    viewport: CanvasViewport | None = None


class BoundInput(PipelineModel):
    slot_id: str
    reading_id: str
    entity_id: str
    accepted_topic: str
    input_key: str
    unit: str | None = None


class PipelineExecutionConfig(PipelineModel):
    schema_version: Literal[1] = 1
    definition: PipelineDefinition
    bindings: list[BoundInput] = Field(min_length=1, max_length=100)
    revision_id: str = Field(min_length=1, max_length=100)
    run_id: str = Field(min_length=1, max_length=100)
    fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_bindings(self) -> "PipelineExecutionConfig":
        slots = [slot.id for slot in self.definition.input_slots]
        actual = [item.slot_id for item in self.bindings]
        if len(slots) != len(set(slots)) or len(actual) != len(set(actual)):
            raise ValueError("Input slot IDs and bindings must be unique")
        if set(slots) != set(actual):
            raise ValueError("Bind every input slot exactly once")
        for attribute in ("reading_id", "accepted_topic", "input_key"):
            values = [getattr(item, attribute) for item in self.bindings]
            if len(values) != len(set(values)):
                raise ValueError(f"Bound {attribute} values must be distinct")
        if len({item.entity_id for item in self.bindings}) != 1:
            raise ValueError("A monitoring run requires one runtime entity")
        by_id = {item.slot_id: item for item in self.bindings}
        if any(
            slot.unit is not None and slot.unit != by_id[slot.id].unit
            for slot in self.definition.input_slots
        ):
            raise ValueError("Bound reading units must exactly match declared units")
        if not fits_json_budget(self, MAX_PIPELINE_EXECUTION_BYTES):
            raise ValueError(
                "Bound pipeline exceeds the 96 KiB executable configuration budget"
            )
        return self


class IssueFix(PipelineModel):
    """A replacement that resolves an issue in the setting the issue names."""

    start: int = Field(ge=0, description="The first character replaced, from 0.")
    end: int = Field(ge=0, description="The character after the last one replaced.")
    text: str = Field(max_length=512, description="What replaces them.")


class PipelineIssue(PipelineModel):
    code: str
    message: str
    node_id: str | None = None
    parameter_path: list[str | int] | None = Field(default=None, max_length=32)
    severity: IssueSeverity = "error"
    fix: IssueFix | None = None


class FeatureDescription(PipelineModel):
    name: str
    slots: list[str]
    minimum: float | None = None
    maximum: float | None = None
    raw: bool = True
    previous: str | None = Field(
        default=None,
        description=(
            "The feature this one continues at the step before, as node.name. "
            "Readings have none, and neither have the features an Aggregate, a "
            "Formula or a projection makes."
        ),
    )
    steps: list[str] = Field(
        default_factory=list,
        description="The steps that changed the feature or its name, in order.",
    )


class PipelineValidation(PipelineModel):
    valid: bool
    issues: list[PipelineIssue] = Field(default_factory=list)
    definition: PipelineDefinition
    order: list[str] = Field(default_factory=list)
    features: dict[str, list[FeatureDescription]] = Field(default_factory=dict)
    fingerprint: str | None = None

    @property
    def incoming(self) -> dict[str, list[str]]:
        edges = sorted(self.definition.edges, key=lambda item: item.order)
        return {
            node.id: [edge.source for edge in edges if edge.target == node.id]
            for node in self.definition.nodes
        }

    @property
    def feature_names(self) -> dict[str, list[str]]:
        return {
            identifier: [item.name for item in columns]
            for identifier, columns in self.features.items()
        }

    def _node_id(self, kind: str) -> str:
        return next(node.id for node in self.definition.nodes if node.kind == kind)

    @property
    def source_id(self) -> str:
        return self._node_id("source")

    @property
    def detector_ids(self) -> list[str]:
        """The detectors in a fixed order, by id; most designs have one."""
        return sorted(
            node.id for node in self.definition.nodes if node.kind == "detector"
        )

    @property
    def detector_inputs(self) -> dict[str, str]:
        """The node whose features each detector reads."""
        incoming = self.incoming
        return {identifier: incoming[identifier][0] for identifier in self.detector_ids}

    @property
    def detector_id(self) -> str:
        """The first detector, which is the only one in most designs."""
        return self.detector_ids[0]

    @property
    def calibration_id(self) -> str | None:
        """The step that turns detector scores into what the policy decides on."""
        return next(
            (node.id for node in self.definition.nodes if node.kind == "calibration"),
            None,
        )

    @property
    def policy_id(self) -> str:
        return self._node_id("policy")

    @property
    def output_id(self) -> str:
        return self._node_id("output")

    @property
    def feature_output_id(self) -> str:
        """The node whose features the first detector reads."""
        return self.incoming[self.detector_id][0]


class PipelineValidationReport(PipelineModel):
    """Bounded presentation of a compilation; executable definitions stay canonical."""

    valid: bool
    issues: list[PipelineIssue] = Field(default_factory=list)
    definition: EditorDefinition | None
    order: list[str] = Field(default_factory=list)
    features: dict[str, list[FeatureDescription]] = Field(default_factory=dict)
    fingerprint: str | None = None
    selected_node_id: str | None = None
    features_complete: bool = True
    provenance_complete: bool = True
    definition_omitted: bool = False
    issues_truncated: bool = False
    preparation_observations: int = Field(
        default=0,
        ge=0,
        description="Observations the Prepare stage takes before anything learns.",
    )
    ready_after: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "For each step of the Prepare stage, the observation, counted from 1, "
            "that gives its first output. Observations a Gate before the step "
            "holds back do not count."
        ),
    )


FieldType = Literal[
    "number",
    "integer",
    "boolean",
    "string",
    "enum",
    "features",
    "rename",
    "number_pair",
    "number_list",
    "component",
    "object",
    "object_list",
    "integer_adjacency",
]


def _empty(value: Any) -> bool:
    return value is None or value is False or value in ("", [], {})


def _without_empty(
    model: BaseModel, data: dict[str, Any], keep: tuple[str, ...] = ()
) -> dict[str, Any]:
    """A dump without the keys that hold their empty default.

    Most settings have no bounds, options, condition or nested settings, and
    most steps no library, twin or method facts. Written out, those nulls are
    the larger part of the catalog. A reader gets the same value from the
    key's default.
    """
    declared = type(model).model_fields
    return {
        key: value
        for key, value in data.items()
        if key in keep
        or not _empty(value)
        or not _empty(declared[key].get_default(call_default_factory=True))
    }


class FieldCondition(PipelineModel):
    """When a setting applies: while another setting of the same step holds one
    of ``equals``, or none of ``not_equals``. Exactly one of the two is given."""

    field: str
    equals: list[str | int | float | bool | None] | None = None
    not_equals: list[str | int | float | bool | None] | None = None

    @model_validator(mode="after")
    def one_comparison(self) -> "FieldCondition":
        if (self.equals is None) == (self.not_equals is None):
            raise ValueError("Give equals or not_equals, not both")
        return self


def shown_when(field: str, *equals: Any, unless: tuple[Any, ...] = ()) -> dict:
    """Schema annotation for a setting that applies only with another one.

    ``Field(json_schema_extra=shown_when("statistic", "quantile"))`` shows the
    setting while ``statistic`` is ``quantile``; ``unless`` names the values
    that hide it instead.
    """
    condition = FieldCondition(
        field=field,
        equals=list(equals) or None,
        not_equals=list(unless) or None,
    )
    return {"x-shown-when": condition.model_dump(mode="json", exclude_none=True)}


class ComponentField(PipelineModel):
    name: str
    label: str
    type: FieldType
    default: Any = None
    required: bool = False
    has_default: bool = False
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: float | None = None
    exclusive_maximum: float | None = None
    options: list[str] | None = None
    nullable: bool = False
    description: str = ""
    # A setting most designs leave alone; editors list it after the others.
    advanced: bool = False
    # The setting only applies with another one; editors hide it otherwise.
    shown_when: FieldCondition | None = None
    fields: list["ComponentField"] = Field(default_factory=list)
    discriminator: str | None = None
    variants: dict[str, list["ComponentField"]] | None = None

    @model_serializer(mode="wrap")
    def _compact(self, handler):
        # A default of null is a default, so it stays where there is one.
        return _without_empty(
            self, handler(self), ("default",) if self.has_default else ()
        )


class PipelineComponent(PipelineModel):
    id: str
    contract_version: Literal[1] = 1
    kind: NodeKind
    group: StepGroup
    label: str
    # One sentence for whoever chooses the step: what it does to the data.
    description: str
    # What is worth knowing beyond that sentence, such as a method's formula.
    details: str = ""
    # The library a detector's model comes from, shown beside its name.
    library: str | None = None
    learning: Learning = "none"
    # The step that does the same job learning the other way, fitted once or
    # continuously; a design moves to it when its detector learns differently.
    counterpart: str | None = None
    # Left out of the catalog listing; one component is read with it.
    parameter_schema: dict[str, Any] = Field(default_factory=dict)
    fields: list[ComponentField] = Field(default_factory=list)
    input_type: PortType | None = "features"
    output_type: PortType = "features"
    # A calibration step's method: its family, what it holds, and its paper.
    family: Literal["conformal", "bayesian"] | None = None
    coverage: Literal["exchangeable", "long_run", "none"] | None = None
    reference: str | None = None

    @model_serializer(mode="wrap")
    def _compact(self, handler):
        return _without_empty(self, handler(self))


class PipelineTemplate(PipelineModel):
    id: str
    name: str
    definition: EditorDefinition
    layout: PipelineLayout


class PipelineCatalog(PipelineModel):
    schema_version: Literal[1] = 1
    catalog_id: str
    authoring_enabled: bool
    components: list[PipelineComponent]
    templates: list[PipelineTemplate]


class ForecastModelCatalog(PipelineModel):
    """What the composer shows about pretrained forecasters.

    ``service`` says whether the deployment has a forecast service and whether
    it answers; ``models`` are its checkpoints with their download state.
    """

    service: Literal["available", "unreachable", "not_deployed"]
    models: list[ForecastModelInfo] = Field(default_factory=list)


class ForecastModelDownload(PipelineModel):
    """The model whose weights the forecast service should download."""

    model: str = Field(min_length=1, max_length=200)


class PipelineCreate(PipelineModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    definition: PipelineDefinition
    layout: PipelineLayout = Field(default_factory=PipelineLayout)


class PipelineDraftSave(PipelineModel):
    expected_version: int = Field(ge=1)
    definition: PipelineDefinition
    layout: PipelineLayout = Field(default_factory=PipelineLayout)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class PipelinePublish(PipelineModel):
    expected_version: int = Field(ge=1)


class PipelineValidateRequest(PipelineModel):
    definition: PipelineDefinition
    selected_node_id: str | None = Field(default=None, min_length=1, max_length=100)


class PipelineMetadataChange(PipelineModel):
    expected_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    archived: bool = False


class PipelineRevisionSummary(PipelineModel):
    id: str
    pipeline_id: str
    number: int
    fingerprint: str
    catalog_id: str
    created_at: datetime


class PipelineRevisionView(PipelineRevisionSummary):
    definition: EditorDefinition


class PipelineRevisionPage(PipelineModel):
    items: list[PipelineRevisionSummary] = Field(max_length=100)
    next_before: int | None = None


class PipelineListQuery(PipelineModel):
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    query: str = Field(default="", max_length=120)
    archived: bool = False


class PipelineRevisionQuery(PipelineModel):
    limit: int = Field(default=25, ge=1, le=100)
    before: int | None = Field(default=None, ge=1)


class PipelineHistoryQuery(PipelineModel):
    limit: int = Field(default=25, ge=1, le=100)


class PipelineSummary(PipelineModel):
    id: str
    name: str
    description: str
    archived: bool
    version: int
    revision_count: int
    created_at: datetime
    updated_at: datetime


class PipelineListPage(PipelineModel):
    items: list[PipelineSummary] = Field(max_length=100)
    next_offset: int | None = None


class PipelineView(PipelineModel):
    id: str
    name: str
    description: str
    archived: bool
    is_template: bool = True
    version: int
    draft: EditorDefinition
    layout: PipelineLayout
    revisions: list[PipelineRevisionSummary] = Field(
        default_factory=list, max_length=100
    )
    revision_next_before: int | None = None
    created_at: datetime
    updated_at: datetime


class PipelineBlockStep(PipelineModel):
    """One step of a block: a component with its settings and its title."""

    component: str = Field(min_length=1, max_length=160)
    contract_version: int = Field(default=1, ge=1)
    params: dict[str, Any] = Field(default_factory=dict)
    label: str | None = Field(default=None, max_length=120)


class PipelineBlockCreate(PipelineModel):
    """A chain of steps to keep under a name; each step feeds the next."""

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    steps: list[PipelineBlockStep] = Field(min_length=1, max_length=MAX_BLOCK_STEPS)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter a block name")
        return value.strip()

    @model_validator(mode="after")
    def bounded_settings(self) -> "PipelineBlockCreate":
        if not fits_json_budget(self.steps, MAX_BLOCK_BYTES):
            raise ValueError(
                f"A block holds at most {MAX_BLOCK_BYTES // 1024} KiB of settings"
            )
        return self


class PipelineBlockView(PipelineModel):
    id: str
    name: str
    description: str
    steps: list[PipelineBlockStep] = Field(max_length=MAX_BLOCK_STEPS)
    created_at: datetime


class PipelineBlockList(PipelineModel):
    """Every block of the library, by name."""

    items: list[PipelineBlockView] = Field(max_length=MAX_BLOCKS)


class PipelineActivationRequest(PipelineModel):
    revision_id: str
    bindings: dict[str, str]
    display_name: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=128)
    replace_service_id: str | None = Field(
        default=None, **public("replace_monitor_id", "replace_service_id")
    )


class PipelineApplyRequest(PipelineModel):
    """Apply the edited configuration without manual library/revision steps."""

    definition: PipelineDefinition
    layout: PipelineLayout = Field(default_factory=PipelineLayout)
    bindings: dict[str, str] = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=128)
    replace_service_id: str | None = Field(
        default=None, **public("replace_monitor_id", "replace_service_id")
    )

    @field_validator("display_name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter a service name")
        return value.strip()


ActivationPhase = Literal[
    "requested",
    "preflighting",
    "validated",
    "retiring",
    "starting",
    "awaiting_heartbeat",
    "succeeded",
    "cancelling",
    "cancelled",
    "failed",
]


class PipelineActivationView(PipelineModel):
    id: str
    phase: ActivationPhase
    service_id: str = Field(**public("monitor_id", "service_id"))
    run_id: str
    predecessor_service_id: str | None = Field(
        **public("predecessor_monitor_id", "predecessor_service_id")
    )
    # Set once a replacement starts retiring its predecessor; from then on
    # cancelling would leave neither monitor running, so it is refused.
    retirement_started: bool = False
    error: str | None
    issues: list[PipelineIssue] = Field(default_factory=list, max_length=64)
    created_at: datetime
    updated_at: datetime


class PipelineReadingMetadata(PipelineModel):
    slot_id: str
    reading_id: str
    label: str
    unit: str | None
    entity_id: str
    device_id: str | None
    entity_label: str
    source_id: str
    source_label: str
    accepted_topic: str
    collection_policy: CollectionPolicy


class PipelineBindingMetadata(PipelineModel):
    schema_version: Literal[1] = 1
    system_schema_version: Literal[1] = 1
    system_revision: int | None
    collection_revision: int
    collection_generation: str
    collection_fingerprint: str
    readings: list[PipelineReadingMetadata]


class PipelineRunSummary(PipelineModel):
    id: str
    service_id: str = Field(**public("monitor_id", "service_id"))
    revision_id: str | None
    predecessor_run_id: str | None
    status: str
    created_at: datetime
    ended_at: datetime | None
    error: str | None = None


class _RunProjection(BaseModel):
    """A saved run as the API shows it; how TACTIC records readings stays inside."""

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)


class PipelineRunInput(_RunProjection):
    """One input slot of a run and the reading bound to it."""

    slot_id: str
    reading_id: str
    unit: str | None = None


class PipelineRunExecution(_RunProjection):
    """What a run executes: its definition and the readings bound to it."""

    schema_version: Literal[1] = 1
    definition: EditorDefinition
    bindings: list[PipelineRunInput]
    revision_id: str
    run_id: str
    fingerprint: str


class PipelineRunReading(_RunProjection):
    """A bound reading as the catalogue described it when the run started."""

    slot_id: str
    reading_id: str
    label: str
    unit: str | None
    device_id: str | None
    device_label: str | None = None
    source_id: str = Field(**public("broker_id", "source_id"))
    source_label: str = Field(**public("broker_label", "source_label"))
    collection_policy: CollectionPolicy

    @model_validator(mode="before")
    @classmethod
    def device_label_from_entity(cls, value: Any) -> Any:
        if isinstance(value, dict) and "entity_label" in value:
            value = dict(value)
            label = value.pop("entity_label")
            if value.get("device_id") is not None:
                value.setdefault("device_label", label)
        return value


class PipelineRunBindings(_RunProjection):
    """The catalogue and recording revisions a run was bound against."""

    schema_version: Literal[1] = 1
    system_revision: int | None = Field(
        **public("catalogue_revision", "system_revision")
    )
    collection_revision: int
    readings: list[PipelineRunReading]


class PipelineRunView(PipelineRunSummary):
    pipeline_id: str | None = None
    execution: PipelineRunExecution | None
    binding_metadata: PipelineRunBindings | None = None


class PipelineHistoryPage(PipelineModel):
    items: list[PipelineRunSummary] = Field(max_length=100)
    next_service_id: str | None = Field(
        default=None, **public("next_monitor_id", "next_service_id")
    )


MAX_TIMELINE_EVENTS = 500


class PipelineRunEventView(PipelineModel):
    """One lifecycle event: a stage change, an activation phase, a crash."""

    occurred_at: datetime
    source: Literal["radar", "tactic"]
    kind: str
    stage: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class PipelineRunTimeline(PipelineModel):
    """What a run went through, oldest event first, and how it ended.

    ``final_status`` is the runtime status the run ended with, kept after its
    service row is purged. ``truncated`` means older events were left out.
    """

    run_id: str
    service_id: str = Field(**public("monitor_id", "service_id"))
    status: str
    error: str | None = None
    created_at: datetime
    ended_at: datetime | None = None
    final_status: dict[str, Any] | None = None
    events: list[PipelineRunEventView] = Field(max_length=MAX_TIMELINE_EVENTS)
    truncated: bool = False


class PipelineServiceView(PipelineModel):
    run: PipelineRunView | None
    history: list[PipelineRunSummary] = Field(max_length=100)
    history_next_service_id: str | None = Field(
        default=None,
        **public("history_next_monitor_id", "history_next_service_id"),
    )
    definition: EditorDefinition
    layout: PipelineLayout
    legacy: bool = False
    validation: PipelineValidationReport | None = None


class MonitorSummary(BaseModel):
    """A monitor as the API shows it; container and Docker details stay inside."""

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    id: str
    display_name: str | None = None
    monitoring_strategy: str | None = None
    model_type: str | None = None
    stream_ids: list[str] = Field(
        default_factory=list,
        description="Catalogue readings the monitor watches.",
        **public("reading_ids", "stream_ids"),
    )
    status: bool = Field(
        description="True while the monitor should run; false once stopped.",
        **public("active", "status"),
    )
    operational_status: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None

    @field_validator("stream_ids", mode="before")
    @classmethod
    def no_readings(cls, value: Any) -> Any:
        return [] if value is None else value


class MonitorDetail(MonitorSummary):
    """One monitor with the configuration it was started with."""

    configuration: dict[str, Any] = Field(default_factory=dict)


class PipelineWorkspace(PipelineModel):
    services: list[MonitorSummary] = Field(**public("monitors", "services"))
    authoring_enabled: bool
    selected_service_id: str | None = Field(
        default=None, **public("selected_monitor_id", "selected_service_id")
    )
    pipeline_state: dict[str, Any] | None = None


class PipelineNodePreview(PipelineModel):
    """One node's bounded inputs and output from a sampled observation pass."""

    input: dict[str, float] | None
    output: dict[str, float] | float | None
    state: str
    reason: str | None = None


class PipelineObservationPasses(PipelineModel):
    score: dict[str, PipelineNodePreview]
    learn: dict[str, PipelineNodePreview]


class ObservedDetector(PipelineModel):
    """One detector's part in a sampled observation of combined detectors."""

    detector_id: str
    score: float | None
    """The detector's own score, higher is more anomalous."""
    surprise: float | None
    """The share of its calibration scores below the score, from 0 to 1."""


class PipelineObservation(PipelineModel):
    sequence_number: int
    timestamp: str
    phase: str
    input_timestamps: dict[str, str]
    passes: PipelineObservationPasses
    detectors: list[ObservedDetector] | None = None
    """Each detector's score and surprise when the policy combines several."""


class PipelineNodeRuntime(PipelineModel):
    state: str
    learn_count: int
    score_count: int
    learn_time_ns: int
    score_time_ns: int
    ready: bool
    learned_updates: int | None
    readiness_observed: int | None
    readiness_required: int | None
    readiness_reason: str | None
    blocked_by: list[str] = Field(default_factory=list)
    error: str | None = None
    rejections: dict[str, int] = Field(default_factory=dict)
    """Observations the step skipped, by reason, such as non_finite or error."""


class PreparationState(PipelineModel):
    """Progress of the Prepare stage, which runs before anything learns."""

    ready: bool
    observed: int
    required: int
    """Observations until the first prepared row reaches the learned stage."""
    rejected: int
    held_back: int = 0
    """Observations a Gate held back from learning and scoring."""
    muted: int = 0
    """Observations scored while a Mute alarms step's condition held."""


class AdaptiveLearningState(PipelineModel):
    state: str
    model_updates: int
    warmup_updates: int
    warmup_required: int
    ready: bool
    reason: str | None


class BatchTrainingState(PipelineModel):
    state: str
    training_samples: int
    calibration_samples: int
    frozen: bool


class PipelineRuntimeState(PipelineModel):
    """What RADAR reports about a running pipeline.

    The workspace serves stored status JSON, so PipelineWorkspace keeps its
    pipeline_state lenient; this model is the browser's type and RADAR's test
    contract.
    """

    run_id: str
    revision_id: str
    fingerprint: str
    captured_at: str
    phase: str
    sequence_number: int
    nodes: dict[str, PipelineNodeRuntime]
    observation: PipelineObservation | None
    truncated: bool
    diagnostic_errors: int
    adaptive_learning: AdaptiveLearningState | None = None
    batch_training: BatchTrainingState | None = None
    preparation: PreparationState | None = None


class ScopeParameters(PipelineModel):
    """Which incoming features a learned step changes, and where its output goes.

    At their defaults the fields are left out of normalized parameters, so a
    design that does not use them keeps its fingerprint.
    """

    apply_to: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        title="Applies to",
        description="The features this step uses. Leave unset to use every feature.",
    )
    result: Literal["replace", "add"] = Field(
        default="replace",
        title="Result",
        description=(
            "Replace the features this step uses, or keep them and add the "
            "step's output as new features."
        ),
    )

    @field_validator("apply_to")
    @classmethod
    def unique_scope(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("List each feature at most once")
        if value is not None and any(not name or len(name) > 120 for name in value):
            raise ValueError("Feature names must contain 1 to 120 characters")
        return value


def _suffix(default: str) -> Any:
    return Field(
        default=default,
        min_length=1,
        max_length=24,
        pattern=r"^[A-Za-z0-9_]+$",
        title="Suffix",
        description="Added features are named <feature>_<suffix>.",
    )


class ElementwiseScopeParameters(ScopeParameters):
    """A step that maps each feature to one value names the features it adds."""

    suffix: str = _suffix("new")


class StandardScalerParameters(ElementwiseScopeParameters):
    suffix: str = _suffix("std")
    with_std: bool = Field(
        default=True,
        description="Divide by the standard deviation. Off only centers each feature.",
    )


class RobustScalerParameters(ElementwiseScopeParameters):
    suffix: str = _suffix("robust")


class RollingRobustScalerParameters(ElementwiseScopeParameters):
    suffix: str = _suffix("robust")
    window_size: int = Field(
        default=256,
        ge=2,
        le=3600,
        description="Recent observations per feature for the median and quartiles.",
    )
    min_samples: int = Field(
        default=32,
        ge=1,
        le=3600,
        description="Observations per feature before the step is ready.",
    )

    @model_validator(mode="after")
    def window_holds_minimum(self) -> "RollingRobustScalerParameters":
        if self.min_samples > self.window_size:
            raise ValueError("min_samples must not exceed window_size")
        return self


class MinMaxScalerParameters(ElementwiseScopeParameters):
    suffix: str = _suffix("minmax")
    feature_range: tuple[float, float] = Field(
        default=(0.0, 1.0),
        description="The range that the lowest and the highest value seen map to.",
    )
    clip: bool = Field(
        default=False,
        description="Keep values beyond the bounds at the ends of the range.",
    )

    @model_validator(mode="after")
    def ordered_range(self) -> "MinMaxScalerParameters":
        if self.feature_range[0] >= self.feature_range[1]:
            raise ValueError("feature_range minimum must be less than maximum")
        return self


class SelectParameters(PipelineModel):
    features: list[str] = Field(
        min_length=1,
        max_length=100,
        description="The features to keep, in this order.",
    )

    @field_validator("features")
    @classmethod
    def unique_features(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Select each feature at most once")
        return value


class RenameParameters(PipelineModel):
    mapping: dict[str, str] = Field(
        description="The new name of each feature to rename."
    )

    @field_validator("mapping")
    @classmethod
    def bounded_names(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 100 or any(
            not name or len(name) > 120 for pair in value.items() for name in pair
        ):
            raise ValueError("Feature names must contain 1 to 120 characters")
        return value


class ProjectionParameters(ScopeParameters):
    n_components: int = Field(
        default=1,
        ge=1,
        le=100,
        description="Features that leave the step. No more than arrive.",
    )
    seed: int | None = Field(
        default=None,
        description="Seed for the random choices. Empty uses the design's seed.",
    )


class OnlinePCAParameters(ScopeParameters):
    n_components: int = Field(
        default=1,
        ge=1,
        le=100,
        description="Features that leave the step. No more than arrive.",
    )
    n0: int = Field(
        default=50,
        ge=2,
        le=1_000_000,
        description=(
            "Observations collected before the first components are set. At "
            "least as many as the components."
        ),
    )
    tol: float = Field(
        default=1e-7,
        gt=0,
        description=(
            "What is left of an observation below this size counts as nothing "
            "new. Rarely needs changing."
        ),
    )
    forgetting_factor: float | None = Field(
        default=None,
        gt=0,
        lt=1,
        description=(
            "Weight of each new observation, between 0 and 1. Empty weighs all "
            "observations alike."
        ),
    )

    @model_validator(mode="after")
    def enough_initial_observations(self) -> "OnlinePCAParameters":
        if self.n0 < self.n_components:
            raise ValueError("n0 must be at least n_components")
        return self


# Prepare steps run once per observation, in arrival order, before anything learns.
PREPARE_WINDOW_LIMIT = 3600


class PrepareScopeParameters(ScopeParameters):
    """A Prepare step maps each feature it uses to one value.

    Left unset, the suffix follows the step's settings, such as diff1 for a
    difference over one observation.
    """

    suffix: str | None = Field(
        default=None,
        min_length=1,
        max_length=24,
        pattern=r"^[A-Za-z0-9_]+$",
        title="Suffix",
        description=(
            "Added features are named <feature>_<suffix>. Leave unset for the "
            "step's short name."
        ),
    )


def _window(
    default: int,
    description: str,
    *,
    minimum: int = 2,
    maximum: int = PREPARE_WINDOW_LIMIT,
    shown: dict | None = None,
) -> Any:
    return Field(
        default=default,
        ge=minimum,
        le=maximum,
        title="Window",
        description=description,
        json_schema_extra=shown,
    )


# Thirty days, in seconds.
MAX_TIME_CONSTANT = 2_592_000


class SmoothParameters(PrepareScopeParameters):
    method: Literal["exponential", "rolling", "time_constant"] = Field(
        default="exponential",
        description=(
            "Exponential weighs recent values more, with alpha = 2 / (window + 1). "
            "Rolling takes the plain mean of the window. Time constant weighs "
            "values by the seconds since they arrived, so readings every second "
            "and every ten are smoothed alike."
        ),
    )
    window_size: int = _window(
        10,
        "Observations to smooth over.",
        shown=shown_when("method", unless=("time_constant",)),
    )
    time_constant: float = Field(
        default=60.0,
        gt=0,
        le=MAX_TIME_CONSTANT,
        title="Time constant",
        description=(
            "Seconds until a lasting change shows to 63% in the result; after "
            "three times as long it shows to 95%."
        ),
        json_schema_extra=shown_when("method", "time_constant"),
    )


class DespikeParameters(PrepareScopeParameters):
    window_size: int = _window(
        11,
        "Recent observations, an odd number, whose median replaces a spike.",
        minimum=5,
        maximum=301,
    )
    threshold: float = Field(
        default=3.0,
        gt=0,
        le=100,
        description=(
            "How many scaled median absolute deviations a value may differ from "
            "the window median before the median replaces it."
        ),
    )

    @field_validator("window_size")
    @classmethod
    def odd_window(cls, value: int) -> int:
        if value % 2 == 0:
            raise ValueError("Choose an odd number, so the window has a middle value")
        return value


class ChangeParameters(PrepareScopeParameters):
    result: Literal["replace", "add"] = Field(
        default="add",
        title="Result",
        description=(
            "Replace the features this step uses, or keep them and add the "
            "step's output as new features."
        ),
    )
    mode: Literal["difference", "percent", "lag"] = Field(
        default="difference",
        description=(
            "Difference x(t) - x(t - lag), percent change against x(t - lag), or "
            "the value lag observations back."
        ),
    )
    lag: int = Field(
        default=1,
        ge=1,
        le=PREPARE_WINDOW_LIMIT,
        description="Observations back to compare with.",
    )


class RollingParameters(PrepareScopeParameters):
    result: Literal["replace", "add"] = Field(
        default="add",
        title="Result",
        description=(
            "Replace the features this step uses, or keep them and add the "
            "step's output as new features."
        ),
    )
    statistic: Literal[
        "mean",
        "median",
        "min",
        "max",
        "std",
        "range",
        "sum",
        "quantile",
        "iqr",
        "mad",
        "slope",
        "zscore",
        "robust_zscore",
        "rank",
        "rms",
        "skewness",
        "kurtosis",
    ] = Field(
        default="mean",
        description=(
            "Statistic of the window. std uses n - 1; iqr is the interquartile "
            "range; mad is the unscaled median absolute deviation. Quantiles "
            "use linear interpolation. Slope is a fitted change per observation. "
            "zscore and robust_zscore say how far the latest value lies from the "
            "window's mean in standard deviations, or from its median in scaled "
            "MADs. rank places the latest value among the window's values, from "
            "0 for the lowest to 1 for the highest. rms is the root mean square; "
            "skewness and kurtosis describe the shape, kurtosis as excess over "
            "a normal distribution."
        ),
    )
    window_size: int = _window(60, "Recent observations the statistic covers.")
    quantile: float = Field(
        default=0.5,
        ge=0,
        le=1,
        description="Quantile to compute, from 0 to 1.",
        json_schema_extra=shown_when("statistic", "quantile"),
    )


def _row_condition(title: str, description: str, *, default: Any = ...) -> Any:
    """A condition over the arriving features that a per-feature step reads."""
    return Field(
        default=default,
        min_length=1,
        max_length=512,
        title=title,
        description=description,
    )


class AccumulateParameters(PrepareScopeParameters):
    result: Literal["replace", "add"] = Field(
        default="add",
        title="Result",
        description=(
            "Keep the features this step uses and add the running value, or "
            "replace them with it."
        ),
    )
    function: Literal["sum", "min", "max", "count"] = Field(
        default="sum",
        description=(
            "Total, minimum, maximum or number of observations since this step's "
            "first accepted observation. Restoring a checkpoint continues the "
            "accumulation; a new run starts over."
        ),
    )
    reset_when: str | None = _row_condition(
        "Reset when",
        "Start over on each observation where this condition holds, such as "
        "dc_current < 1. That observation is the first of the new "
        "accumulation. Leave empty to never start over.",
        default=None,
    )


class HoldParameters(PrepareScopeParameters):
    """Keep each feature's value from the last observation a condition held."""

    result: Literal["replace", "add"] = Field(
        default="add",
        title="Result",
        description=(
            "Keep the features this step uses and add the held value, or "
            "replace them with it."
        ),
    )
    update_when: str = _row_condition(
        "Update when",
        "Take the current value on each observation where this condition "
        "holds, such as valid == 1, and keep it until the next one. The "
        "first observation is always taken.",
    )


class RelationParameters(PrepareScopeParameters):
    """How each feature moves with one other feature over recent observations."""

    result: Literal["replace", "add"] = Field(
        default="add",
        title="Result",
        description=(
            "Keep the features this step uses and add the statistic, or "
            "replace them with it."
        ),
    )
    against: str = Field(
        min_length=1,
        max_length=120,
        title="Against",
        description="The feature every other feature is compared with.",
    )
    statistic: Literal["correlation", "covariance", "slope", "residual"] = Field(
        default="correlation",
        description=(
            "Correlation, from -1 to 1, and covariance, with n - 1, say how the "
            "feature moves with the other one. Slope is the feature's fitted "
            "change per unit of the other one. Residual is how far the latest "
            "value lies from that fitted line. A window where either feature "
            "stays flat gives a correlation and a slope of 0."
        ),
    )
    window_size: int = _window(
        60, "Recent observations the statistic covers.", minimum=3
    )


MAX_CALCULATION_LINES = 32


class CalculateParameters(PipelineModel):
    """Several features computed in order, each line as name = formula."""

    formulas: str = Field(
        min_length=1,
        max_length=4096,
        title="Formulas",
        description=(
            "One feature per line, written name = formula, such as "
            "power = dc_voltage * dc_current. Lines run from top to bottom, so a "
            "line can read the features above it. A name that already arrives "
            "is replaced; a new one is added. Lines that start with # are notes."
        ),
    )


class TimeParameters(PipelineModel):
    """Features of the time an observation was measured at."""

    elapsed: bool = Field(
        default=True,
        title="Seconds since the previous observation",
        description=(
            "Adds dt. The first observation has none before it, so the step is "
            "ready after two."
        ),
    )
    hour: bool = Field(
        default=False,
        title="Hour of day",
        description=(
            "Adds hour, from 0 at midnight up to 24, with minutes as a fraction."
        ),
    )
    weekday: bool = Field(
        default=False,
        title="Day of week",
        description="Adds weekday, from 1 for Monday to 7 for Sunday.",
    )
    daily_cycle: bool = Field(
        default=False,
        title="Daily cycle",
        description=(
            "Adds hour_sin and hour_cos, the time of day on a circle, where "
            "23:59 lies next to 0:00."
        ),
    )
    weekly_cycle: bool = Field(
        default=False,
        title="Weekly cycle",
        description=(
            "Adds weekday_sin and weekday_cos, the time of week on a circle, "
            "where Sunday night lies next to Monday morning."
        ),
    )
    timezone: str = Field(
        default="UTC",
        min_length=1,
        max_length=64,
        title="Time zone",
        description=(
            "The clock the hour and the weekday follow, such as Europe/Berlin, "
            "with its daylight saving time."
        ),
    )

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        if value == "UTC":
            return value
        try:
            ZoneInfo(value)
        except (KeyError, ValueError, OSError):
            raise ValueError(
                "Unknown time zone. Write a name such as Europe/Berlin, or UTC."
            ) from None
        return value

    @model_validator(mode="after")
    def some_feature(self):
        if not any(getattr(self, name) for name in TIME_SETTINGS):
            raise ValueError("Choose at least one time feature.")
        return self


# The settings of a Time features step that each add features, in output order.
TIME_SETTINGS = ("elapsed", "hour", "weekday", "daily_cycle", "weekly_cycle")


class MathParameters(PrepareScopeParameters):
    function: Literal["log", "log1p", "sqrt", "abs", "square", "linear"] = Field(
        default="log",
        description=(
            "log needs values above 0, log1p above -1 and sqrt at least 0; "
            "linear computes scale * x + offset."
        ),
    )
    scale: float = Field(
        default=1.0,
        description="Factor of linear.",
        json_schema_extra=shown_when("function", "linear"),
    )
    offset: float = Field(
        default=0.0,
        description="Constant added by linear.",
        json_schema_extra=shown_when("function", "linear"),
    )


class RangeParameters(PrepareScopeParameters):
    low: float | None = Field(
        default=0.0, description="Smallest accepted value; none leaves it open."
    )
    high: float | None = Field(
        default=1.0, description="Largest accepted value; none leaves it open."
    )
    action: Literal["clip", "skip"] = Field(
        default="clip",
        description=(
            "Clip moves values outside the range to its nearest end. Skip drops "
            "the whole observation and counts it as a coverage gap."
        ),
    )

    @model_validator(mode="after")
    def ordered_bounds(self) -> "RangeParameters":
        if self.low is None and self.high is None:
            raise ValueError("Set low, high or both")
        if self.low is not None and self.high is not None and self.low >= self.high:
            raise ValueError("low must be less than high")
        if self.action == "skip" and self.result == "add":
            raise ValueError(
                "Skipping leaves values unchanged, so there is nothing to add. "
                "Choose Replace values."
            )
        return self


COMBINED_NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"
FORMULA_SUFFIX = "formula"
"""What a Formula for each feature appends to the names it adds, by default."""
FORMULA_VARIABLE = "x"
"""The name that stands for each feature in a Formula for each feature."""


def _combined_name(default: str) -> Any:
    return Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=COMBINED_NAME_PATTERN,
        title="Name",
        description=(
            "Name of the computed feature: letters, digits and underscores, "
            f"not starting with a digit. Leave unset for {default}."
        ),
    )


def _keeps(what: str) -> Any:
    return Field(
        default="add",
        title="Result",
        description=(
            f"Keep {what} and add the computed feature, or replace them with it."
        ),
    )


class AggregateParameters(ScopeParameters):
    """One feature computed across the features this step uses."""

    result: Literal["replace", "add"] = _keeps("the features this step uses")
    function: Literal["mean", "sum", "min", "max", "std", "range"] = Field(
        default="mean",
        description=(
            "Computed across the features of each observation; std is the sample "
            "standard deviation and range is max minus min."
        ),
    )
    name: str | None = _combined_name("the function's name, such as mean")


class FormulaParameters(PipelineModel):
    """One feature computed from the features arriving at the step."""

    expression: str = Field(
        min_length=1,
        max_length=512,
        title="Formula",
        description=(
            "Arithmetic over the features arriving here, such as "
            "dc_voltage * dc_current, with + - * / ^, parentheses and functions "
            "such as abs, sqrt, log, round, mod, min, max, mean and "
            "if(condition, when_true, when_false); typing lists them all. "
            "Only the chosen branch of if is evaluated. Write a name with other "
            "characters between backticks. In a formula for each feature, x "
            "stands for that feature."
        ),
    )
    name: str | None = _combined_name("formula")
    result: Literal["replace", "add"] = _keeps("the features the formula reads")
    apply_to: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        title="For each",
        description=(
            "Compute the formula once for each of these features, with x standing "
            "for the feature, such as x / mean - 1. Leave unset to compute one "
            "feature."
        ),
    )
    suffix: str | None = Field(
        default=None,
        min_length=1,
        max_length=24,
        pattern=r"^[A-Za-z0-9_]+$",
        title="Suffix",
        description=(
            "For each feature, keeping features adds <feature>_<suffix>. Leave "
            f"unset for {FORMULA_SUFFIX}."
        ),
    )

    @field_validator("apply_to")
    @classmethod
    def unique_features(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("List each feature at most once")
        if value is not None and any(not name or len(name) > 120 for name in value):
            raise ValueError("Feature names must contain 1 to 120 characters")
        return value

    @model_validator(mode="after")
    def one_naming(self) -> "FormulaParameters":
        if self.apply_to is not None and self.name is not None:
            raise ValueError(
                "A formula for each feature names its features with Suffix; "
                "leave Name empty"
            )
        return self


class GateParameters(PipelineModel):
    """Hold back the observations a condition rejects."""

    condition: str = Field(
        min_length=1,
        max_length=512,
        title="Condition",
        description=(
            "Observations where it is false are recorded but neither learned nor "
            "scored, such as dc_current > 1. Compare with < <= > >= == != and "
            "join with and, or and not."
        ),
    )


class MuteParameters(PipelineModel):
    """Raise no alarm for the observations a condition accepts."""

    condition: str = Field(
        min_length=1,
        max_length=512,
        title="Condition",
        description=(
            "Observations where it is true are learned and scored as usual, and "
            "an alarm for one of them is kept as muted instead of raised, such "
            "as speed < 100. Compare with < <= > >= == != and join with and, or "
            "and not."
        ),
    )


class ConstantParameters(PipelineModel):
    name: str | None = _combined_name("constant")
    value: float = Field(
        default=0.0,
        description="Add this named value to each observation for later steps to use.",
    )


class ConditionParameters(PipelineModel):
    name: str | None = _combined_name("condition")
    condition: str = Field(
        min_length=1,
        max_length=512,
        title="Condition",
        description=(
            "Add 1 when this condition holds and 0 otherwise, keeping the observation. "
            "Use comparisons with and, or, not; later steps can read the flag "
            "with flag == 1."
        ),
    )


class SetFeatureParameters(PipelineModel):
    name: str = Field(
        default="feature",
        min_length=1,
        max_length=120,
        title="Name",
        description=(
            "The feature to calculate. An existing one of that name is replaced."
        ),
    )
    expression: str = Field(
        min_length=1,
        max_length=512,
        title="Formula",
        description=(
            "Compute this feature from the incoming values. Replace only the named "
            "feature if it exists, or add it. All other features stay unchanged. "
            "Use if(condition, when_true, when_false) to choose a value."
        ),
    )


class ExpectedValueParameters(ScopeParameters):
    """How far one feature lies from the value the other features imply.

    The step fits the target as a weighted sum of the other features and a
    constant, and gives the residual: the target minus that expected value.
    """

    target: str = Field(
        min_length=1,
        max_length=120,
        title="Target",
        description="The feature whose value is expected from the others.",
    )
    apply_to: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        title="Expected from",
        description=(
            "The features the target is expected from. Leave unset to use every "
            "other feature."
        ),
    )
    result: Literal["replace", "add"] = Field(
        default="replace",
        title="Result",
        description=(
            "Replace the target and the features it is expected from with the "
            "residual, or keep them and add it."
        ),
    )
    name: str | None = _combined_name("<target>_residual")


class OnlineExpectedValueParameters(ExpectedValueParameters):
    """The fit follows every observation, by recursive least squares."""

    forgetting: float = Field(
        default=1.0,
        gt=0,
        le=1,
        description=(
            "How much earlier observations count at every update. 1 weighs every "
            "observation alike; 0.999 remembers roughly the last 1,000, so the "
            "fit follows slow drift. Below 1, readings that stop varying for "
            "long make the fit unstable, so keep 1 for readings that rest."
        ),
    )
