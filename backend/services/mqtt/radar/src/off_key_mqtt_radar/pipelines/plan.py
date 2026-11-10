"""Runtime view of the shared compiler's canonical execution plan."""

from dataclasses import dataclass, field
from functools import cached_property

from off_key_core.models.pipeline_parameters import fusion_mode
from off_key_core.models.pipeline_prepare import StageSplit, stage_split
from off_key_core.models.pipelines import compile_pipeline, execution_fingerprint
from off_key_core.schemas.pipelines import PipelineExecutionConfig, PipelineValidation

from ..execution_errors import ObservationRejected


@dataclass
class ExecutionPlan:
    execution: PipelineExecutionConfig
    compiled: PipelineValidation = field(init=False)
    _nodes: dict = field(init=False, repr=False)
    _parents: dict = field(init=False, repr=False)
    _names: dict = field(init=False, repr=False)
    _feature_nodes: list = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.compiled = compile_pipeline(self.execution.definition)
        if self.execution.fingerprint != execution_fingerprint(
            self.execution.definition, self.execution.bindings
        ):
            raise ValueError("Bound executable fingerprint differs from its definition")
        self._nodes = {node.id: node for node in self.compiled.definition.nodes}
        self._parents = self.compiled.incoming
        self._names = self.compiled.feature_names
        self._feature_nodes = [
            self._nodes[identifier]
            for identifier in self.compiled.order
            if self._nodes[identifier].kind in {"transform", "merge"}
        ]

    @property
    def nodes(self):
        return self._nodes

    def parents(self, identifier: str) -> list[str]:
        return self._parents[identifier]

    def names(self, identifier: str) -> list[str]:
        return self._names[identifier]

    # Derived IDs are cached lazily: plans unpickled from older checkpoints
    # never ran __post_init__ beyond the fields they stored.
    @cached_property
    def source_id(self) -> str:
        return self.compiled.source_id

    @cached_property
    def detector_id(self) -> str:
        return self.compiled.detector_id

    @cached_property
    def detector_ids(self) -> list[str]:
        """Every detector, in the order the run keeps them; most designs have one."""
        return self.compiled.detector_ids

    @cached_property
    def detector_inputs(self) -> dict[str, str]:
        """The node whose features each detector reads."""
        return self.compiled.detector_inputs

    @property
    def fused(self) -> bool:
        """Several detectors feed the policy, which combines them."""
        return len(self.detector_ids) > 1

    @cached_property
    def fusion(self) -> str:
        """How the calibration step combines detectors: max or mean."""
        identifier = self.compiled.calibration_id or self.policy_id
        return fusion_mode(self.nodes[identifier].params)

    def detector_features(self, detector_id: str) -> list[str]:
        """The features one detector scores, in their order."""
        return self.names(self.detector_inputs[detector_id])

    def reads(self, detector_id: str) -> frozenset[str]:
        """The nodes whose features reach a detector, its input included."""
        needed: set[str] = set()
        pending = [self.detector_inputs[detector_id]]
        while pending:
            identifier = pending.pop()
            if identifier not in needed:
                needed.add(identifier)
                pending.extend(self.parents(identifier))
        return frozenset(needed)

    def owned(self, detector_id: str) -> frozenset[str]:
        """The nodes this detector's graph reports, as the first one to read them.

        Adaptive detectors each learn their own copy of a step they share, so
        only the first copy counts in the diagnostics.
        """
        earlier = self.detector_ids[: self.detector_ids.index(detector_id)]
        return self.reads(detector_id).difference(
            *(self.reads(identifier) for identifier in earlier)
        )

    @cached_property
    def policy_id(self) -> str:
        return self.compiled.policy_id

    @cached_property
    def output_id(self) -> str:
        return self.compiled.output_id

    @cached_property
    def feature_output_id(self) -> str:
        return self.compiled.feature_output_id

    @cached_property
    def stage(self) -> StageSplit | None:
        """The Prepare stage, when the design has one."""
        return stage_split(self.compiled)

    @cached_property
    def learned_nodes(self) -> list:
        """Feature nodes after the Prepare stage, in compiled order."""
        if self.stage is None:
            return self._feature_nodes
        steps = set(self.stage.steps)
        return [node for node in self._feature_nodes if node.id not in steps]

    @cached_property
    def input_columns(self) -> list[str]:
        """What the learned stage reads: the readings, or the prepared features."""
        if self.stage is None:
            return self.names(self.source_id)
        return self.stage.columns(self._names)

    @cached_property
    def _expected_inputs(self) -> frozenset[str]:
        return frozenset(item.input_key for item in self.execution.bindings)

    @cached_property
    def _slot_inputs(self) -> list[tuple[str, str]]:
        by_slot = {item.slot_id: item.input_key for item in self.execution.bindings}
        return [
            (slot.id, by_slot[slot.id]) for slot in self.compiled.definition.input_slots
        ]

    def bind(self, data: dict[str, float]) -> dict[str, float]:
        expected = self._expected_inputs
        if set(data) != expected:
            raise ObservationRejected(
                "Pipeline inputs differ from the bound reading schema; "
                f"missing={sorted(expected - data.keys())}, "
                f"extra={sorted(data.keys() - expected)}"
            )
        return {slot: float(data[key]) for slot, key in self._slot_inputs}

    @property
    def output_features(self) -> list[str]:
        return self.names(self.feature_output_id)
