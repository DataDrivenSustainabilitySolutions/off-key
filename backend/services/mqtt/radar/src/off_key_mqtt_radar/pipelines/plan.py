"""Runtime view of the shared compiler's canonical execution plan."""

from dataclasses import dataclass, field

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

    @property
    def feature_nodes(self):
        return self._feature_nodes

    def parents(self, identifier: str) -> list[str]:
        return self._parents[identifier]

    def names(self, identifier: str) -> list[str]:
        return self._names[identifier]

    def bind(self, data: dict[str, float]) -> dict[str, float]:
        expected = {item.input_key for item in self.execution.bindings}
        if set(data) != expected:
            raise ObservationRejected(
                "Pipeline inputs differ from the bound reading schema; "
                f"missing={sorted(expected - data.keys())}, "
                f"extra={sorted(data.keys() - expected)}"
            )
        by_slot = {item.slot_id: item for item in self.execution.bindings}
        return {
            slot.id: float(data[by_slot[slot.id].input_key])
            for slot in self.compiled.definition.input_slots
        }

    @property
    def output_features(self) -> list[str]:
        return self.names(self.compiled.feature_output_id)
