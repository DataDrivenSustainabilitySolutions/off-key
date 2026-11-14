"""Contracts for building a design step by step, as a program or an agent does.

The editor in the browser reads the whole catalog and saves a whole design. A
caller that builds a design in steps wants less at a time: the few components
that fit a purpose, and one small change to a design after another.
"""

from typing import Annotated, Any, Literal

from pydantic import Field, model_serializer

from .pipeline_versions import Learning
from .pipelines import (
    EditorDefinition,
    NodeKind,
    PipelineDefinition,
    PipelineLayout,
    PipelineModel,
    PipelineValidationReport,
    PortType,
    StepGroup,
    _without_empty,
)

STEP_ID = r"^[A-Za-z][A-Za-z0-9_-]*$"


class ComponentSummary(PipelineModel):
    """A component in a few lines: enough to choose it, not to configure it."""

    id: str
    kind: NodeKind
    group: StepGroup
    label: str
    description: str
    library: str | None = None
    learning: Learning = "none"
    input_type: PortType | None = "features"
    output_type: PortType = "features"
    settings: list[str] = Field(
        default_factory=list,
        description="Names of its settings. Read the component for what each does.",
    )

    @model_serializer(mode="wrap")
    def _compact(self, handler):
        return _without_empty(self, handler(self))


class ComponentSearchQuery(PipelineModel):
    """What to look for among the components, and how many to answer with."""

    query: str = Field(
        default="",
        max_length=200,
        description=(
            "What the step should do, in a few words, such as calm noise or "
            "seasonal forecast. Empty lists every component the filters leave."
        ),
    )
    kind: NodeKind | None = None
    group: StepGroup | None = None
    learning: Learning | None = None
    limit: int = Field(default=10, ge=1, le=100)


class ComponentSearchPage(PipelineModel):
    """The components that fit a search, the best fit first."""

    catalog_id: str
    total: int = Field(
        ge=0, description="How many components fit; the page may hold fewer."
    )
    components: list[ComponentSummary]


class _Edit(PipelineModel):
    """One small change to a design."""


class AddStep(_Edit):
    """Add a step. With ``after`` and ``before`` it goes on the connection
    between the two. With one of them, a step that hands its features on goes
    into the one connection on that side, so ``after: input`` puts it between
    the input and the step that followed it; where that side has several
    connections, or none, it is connected on that side only."""

    op: Literal["add_step"]
    component: str = Field(
        min_length=1, max_length=160, description="Id of a component in the catalog."
    )
    id: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=STEP_ID,
        description="Name of the new step. Left out, it is made from the component.",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Settings that differ from the component's defaults.",
    )
    label: str | None = Field(default=None, max_length=120)
    after: str | None = Field(
        default=None, description="Id of the step whose output the new step takes."
    )
    before: str | None = Field(
        default=None, description="Id of the step that takes the new step's output."
    )


class RemoveStep(_Edit):
    """Remove a step with its connections. A step with one input hands that
    input on to the steps that took its output, unless ``reconnect`` is false."""

    op: Literal["remove_step"]
    id: str
    reconnect: bool = True


class ReplaceStep(_Edit):
    """Make a step another component. Its id and connections stay, its
    settings start from the new component's defaults."""

    op: Literal["replace_step"]
    id: str
    component: str = Field(min_length=1, max_length=160)
    params: dict[str, Any] = Field(default_factory=dict)


class SetParams(_Edit):
    """Change settings of a step. The settings named in ``params`` take the
    given values, those named in ``unset`` return to their defaults, and the
    others stay."""

    op: Literal["set_params"]
    id: str
    params: dict[str, Any] = Field(default_factory=dict)
    unset: list[str] = Field(default_factory=list, max_length=64)


class SetLabel(_Edit):
    """Title a step, or take its title away with null."""

    op: Literal["set_label"]
    id: str
    label: str | None = Field(max_length=120)


class Connect(_Edit):
    """Connect the output of one step to the input of another. A step with a
    single input takes the new connection in place of the one it had."""

    op: Literal["connect"]
    source: str
    target: str


class Disconnect(_Edit):
    """Remove the connection between two steps."""

    op: Literal["disconnect"]
    source: str
    target: str


class AddInput(_Edit):
    """Declare a reading the design takes in."""

    op: Literal["add_input"]
    id: str = Field(min_length=1, max_length=100, pattern=STEP_ID)
    label: str | None = Field(default=None, min_length=1, max_length=120)
    unit: str | None = Field(default=None, max_length=32)


class RemoveInput(_Edit):
    """Take a reading out of the design's inputs."""

    op: Literal["remove_input"]
    id: str


class SetSettings(_Edit):
    """Change how much the design learns from before it scores, or the seed
    its random choices start from. What is left out stays as it is."""

    op: Literal["set_settings"]
    training_window_size: int | None = Field(default=None, ge=2, le=1_000_000)
    calibration_window_size: int | None = Field(default=None, ge=1, le=1_000_000)
    seed: int | None = None


class AddNote(_Edit):
    """Put a note on the canvas, above the step it is about. Notes say why a
    design is built the way it is; they change nothing about what it computes."""

    op: Literal["add_note"]
    text: str = Field(min_length=1, max_length=2000)
    beside: str | None = Field(
        default=None, description="Id of the step the note is about."
    )


class RemoveNote(_Edit):
    """Take a note off the canvas."""

    op: Literal["remove_note"]
    id: str


DesignEdit = Annotated[
    AddStep
    | RemoveStep
    | ReplaceStep
    | SetParams
    | SetLabel
    | Connect
    | Disconnect
    | AddInput
    | RemoveInput
    | SetSettings
    | AddNote
    | RemoveNote,
    Field(discriminator="op"),
]


class DesignEditRequest(PipelineModel):
    """A design and the changes to make to it, in order."""

    definition: PipelineDefinition = Field(default_factory=PipelineDefinition)
    layout: PipelineLayout = Field(default_factory=PipelineLayout)
    edits: list[DesignEdit] = Field(min_length=1, max_length=100)


class DesignEditResult(PipelineModel):
    """The design after the changes, and what a check says about it."""

    definition: EditorDefinition
    layout: PipelineLayout
    added: list[str] = Field(
        default_factory=list,
        description="Ids of the steps and notes the edits added, in their order.",
    )
    also: list[str] = Field(
        default_factory=list,
        description=(
            "What the edits changed beyond the steps they named, such as the "
            "alarm policy that follows a new calibration step."
        ),
    )
    report: PipelineValidationReport
