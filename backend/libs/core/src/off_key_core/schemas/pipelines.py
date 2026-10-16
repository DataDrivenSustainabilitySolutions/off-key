"""Versioned monitoring designs; safe to import in the control plane."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from off_key_core.utils.json_budget import fits_json_budget

from .collection_policy import CollectionPolicy

PipelineStrategy = Literal["static_baseline", "adaptive_stream"]
NodeKind = Literal["source", "transform", "merge", "detector", "policy", "output"]
PortType = Literal["features", "scores", "p_values", "decisions", "evidence"]
Identifier = str
MAX_PIPELINE_EXECUTION_BYTES = 96 * 1024


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
    training_window_size: int = Field(default=1200, ge=2, le=1_000_000)
    calibration_window_size: int = Field(default=360, ge=1, le=1_000_000)
    seed: int | None = 42
    conformal_strategy: Literal["split"] = "split"


class PipelineDefinition(PipelineModel):
    schema_version: Literal[1] = 1
    strategy: PipelineStrategy = "static_baseline"
    input_slots: list[InputSlot] = Field(default_factory=list, max_length=100)
    # Drafts intentionally allow incomplete/disconnected graphs.
    nodes: list[PipelineNode] = Field(default_factory=list, max_length=64)
    edges: list[PipelineEdge] = Field(default_factory=list, max_length=128)
    settings: PipelineSettings = Field(default_factory=PipelineSettings)


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


class PipelineIssue(PipelineModel):
    code: str
    message: str
    node_id: str | None = None


class FeatureDescription(PipelineModel):
    name: str
    slots: list[str]
    minimum: float | None = None
    maximum: float | None = None
    raw: bool = True


class PipelineValidation(PipelineModel):
    valid: bool
    issues: list[PipelineIssue] = Field(default_factory=list)
    definition: PipelineDefinition
    order: list[str] = Field(default_factory=list)
    features: dict[str, list[FeatureDescription]] = Field(default_factory=dict)
    fingerprint: str | None = None

    @property
    def incoming(self) -> dict[str, list[str]]:
        return {
            node.id: [
                edge.source
                for edge in sorted(self.definition.edges, key=lambda item: item.order)
                if edge.target == node.id
            ]
            for node in self.definition.nodes
        }

    @property
    def feature_names(self) -> dict[str, list[str]]:
        return {
            identifier: [item.name for item in columns]
            for identifier, columns in self.features.items()
        }

    @property
    def lineage(self) -> dict[str, dict[str, list[str]]]:
        return {
            identifier: {item.name: item.slots for item in columns}
            for identifier, columns in self.features.items()
        }

    def _node_id(self, kind: str) -> str:
        return next(node.id for node in self.definition.nodes if node.kind == kind)

    @property
    def source_id(self) -> str:
        return self._node_id("source")

    @property
    def detector_id(self) -> str:
        return self._node_id("detector")

    @property
    def policy_id(self) -> str:
        return self._node_id("policy")

    @property
    def output_id(self) -> str:
        return self._node_id("output")

    @property
    def feature_output_id(self) -> str:
        return self.incoming[self.detector_id][0]

    @property
    def model_type(self) -> str:
        return next(
            node.component.removeprefix("detector:")
            for node in self.definition.nodes
            if node.kind == "detector"
        )

    @property
    def model_params(self) -> dict[str, Any]:
        return next(
            node.params for node in self.definition.nodes if node.kind == "detector"
        )


class PipelineValidationReport(PipelineModel):
    """Bounded presentation of a compilation; executable definitions stay canonical."""

    valid: bool
    issues: list[PipelineIssue] = Field(default_factory=list)
    definition: PipelineDefinition | None
    order: list[str] = Field(default_factory=list)
    features: dict[str, list[FeatureDescription]] = Field(default_factory=dict)
    fingerprint: str | None = None
    selected_node_id: str | None = None
    features_complete: bool = True
    provenance_complete: bool = True
    definition_omitted: bool = False
    issues_truncated: bool = False


class ComponentField(PipelineModel):
    name: str
    label: str
    type: Literal[
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
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    options: list[str] | None = None
    nullable: bool = False
    description: str = ""
    fields: list["ComponentField"] = Field(default_factory=list)
    discriminator: str | None = None
    variants: dict[str, list["ComponentField"]] | None = None


class PipelineComponent(PipelineModel):
    id: str
    contract_version: Literal[1] = 1
    kind: NodeKind
    label: str
    description: str
    strategies: list[PipelineStrategy]
    parameter_schema: dict[str, Any] = Field(default_factory=dict)
    fields: list[ComponentField] = Field(default_factory=list)
    input_type: PortType | None = "features"
    output_type: PortType = "features"


class PipelineTemplate(PipelineModel):
    id: str
    name: str
    definition: PipelineDefinition
    layout: PipelineLayout


class PipelineCatalog(PipelineModel):
    schema_version: Literal[1] = 1
    catalog_id: str
    authoring_enabled: bool
    components: list[PipelineComponent]
    templates: list[PipelineTemplate]


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
    definition: PipelineDefinition


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
    strategy: PipelineStrategy
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
    version: int
    draft: PipelineDefinition
    layout: PipelineLayout
    revisions: list[PipelineRevisionSummary] = Field(
        default_factory=list, max_length=100
    )
    revision_next_before: int | None = None
    created_at: datetime
    updated_at: datetime


class PipelineActivationRequest(PipelineModel):
    revision_id: str
    bindings: dict[str, str]
    display_name: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=128)
    replace_service_id: str | None = None


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
    service_id: str
    run_id: str
    predecessor_service_id: str | None
    error: str | None
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
    service_id: str
    revision_id: str | None
    predecessor_run_id: str | None
    status: str
    created_at: datetime
    ended_at: datetime | None
    error: str | None = None


class PipelineRunView(PipelineRunSummary):
    pipeline_id: str | None = None
    execution: PipelineExecutionConfig | None
    binding_metadata: PipelineBindingMetadata | None = None


class PipelineHistoryPage(PipelineModel):
    items: list[PipelineRunSummary] = Field(max_length=100)
    next_service_id: str | None = None


class PipelineServiceView(PipelineModel):
    run: PipelineRunView | None
    history: list[PipelineRunSummary] = Field(max_length=100)
    history_next_service_id: str | None = None
    definition: PipelineDefinition
    layout: PipelineLayout
    legacy: bool = False
    validation: PipelineValidationReport | None = None


class PipelineWorkspace(PipelineModel):
    services: list[dict[str, Any]]
    authoring_enabled: bool
    selected_service_id: str | None = None
    pipeline_state: dict[str, Any] | None = None


class StandardScalerParameters(PipelineModel):
    with_std: bool = True


class MinMaxScalerParameters(PipelineModel):
    feature_range: tuple[float, float] = (0.0, 1.0)
    clip: bool = False

    @model_validator(mode="after")
    def ordered_range(self) -> "MinMaxScalerParameters":
        if self.feature_range[0] >= self.feature_range[1]:
            raise ValueError("feature_range minimum must be less than maximum")
        return self


class SelectParameters(PipelineModel):
    features: list[str] = Field(min_length=1, max_length=100)

    @field_validator("features")
    @classmethod
    def unique_features(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Select each feature at most once")
        return value


class RenameParameters(PipelineModel):
    mapping: dict[str, str]

    @field_validator("mapping")
    @classmethod
    def bounded_names(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 100 or any(
            not name or len(name) > 120 for pair in value.items() for name in pair
        ):
            raise ValueError("Feature names must contain 1 to 120 characters")
        return value


class ProjectionParameters(PipelineModel):
    n_components: int = Field(default=1, ge=1, le=100)
    seed: int | None = None


class OnlinePCAParameters(PipelineModel):
    n_components: int = Field(default=1, ge=1, le=100)
    n0: int = Field(default=50, ge=2, le=1_000_000)
    tol: float = Field(default=1e-7, gt=0)
    forgetting_factor: float | None = Field(default=None, gt=0, lt=1)

    @model_validator(mode="after")
    def enough_initial_observations(self) -> "OnlinePCAParameters":
        if self.n0 < self.n_components:
            raise ValueError("n0 must be at least n_components")
        return self
